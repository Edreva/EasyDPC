# =============================================================================
# qDPC NDTiff Parser
#
# Copyright (C) 2026 Ewan Drever-Smith
# Free to use, redistribute and modify under GPLv3, see LICENSE.md for details. 
# =============================================================================

"""
NDTiff metadata parser and data accessor.
"""


from pathlib import Path

import numpy as np
from tkinter import simpledialog
import ndstorage as nd

from .qdpc_processing_parameters import QDPCProcessingParameters
from .camera_info_manager import CameraInfoManager


class NDTiffParser:
    """
    Parses metadata from an NDTiff dataset and exposes the DPC data and
    parameters required for qDPC processing.
    """

    def __init__(
        self,
        ndtiff_path: Path | str,
        existing_params: QDPCProcessingParameters | None = None,
    ) -> None:
        self.ndtiff_path = Path(ndtiff_path)
        self.dataset = nd.Dataset(str(self.ndtiff_path))
        self._parse_metadata(existing_params)

    def _parse_metadata(self, existing_params: QDPCProcessingParameters | None) -> None:
        self._parse_camera_name()
        axis_order, image_shape = self._parse_axes_order_and_shape()
        channel_names, dpc_channel_idxs, dpc_rotations = self._parse_dpc_channels()

        new_dpc_rotations = dpc_rotations
        if new_dpc_rotations is None:
            n = len(dpc_channel_idxs)
            new_dpc_rotations = [int(i * 360 / n) for i in range(n)]

        camera_pixel_size = self._get_camera_pixel_size()
        z_step = self._parse_z_step()

        if existing_params is not None:
            # Update only the file-specific fields. Preserve user-set values.
            existing_params.input_file_path = self.ndtiff_path
            existing_params.image_shape = image_shape
            existing_params.image_axis_order = axis_order
            existing_params.channel_names = channel_names
            existing_params.dpc_channel_idxs = dpc_channel_idxs
            existing_params.camera_name = self.camera_name
            existing_params.dpc_rotations = existing_params.dpc_rotations if dpc_rotations is None else dpc_rotations
            existing_params.camera_pixel_size = camera_pixel_size if camera_pixel_size is not None else existing_params.camera_pixel_size
            existing_params.z_step = z_step
            self.dpc_parameters = existing_params
        else:
            self.dpc_parameters = QDPCProcessingParameters(
                input_file_path=self.ndtiff_path,
                image_shape=image_shape,
                image_axis_order=axis_order,
                channel_names=channel_names,
                camera_name=self.camera_name,
                dpc_channel_idxs=dpc_channel_idxs,
                dpc_rotations=new_dpc_rotations,
                camera_pixel_size=camera_pixel_size,
                z_step=z_step,
            )

    def _parse_z_step(self) -> float | None:
        return self.dataset.summary_metadata.get("z-step_um", None)

    def _parse_camera_name(self) -> None:
        raw_metadata = self.dataset.read_metadata(0, 0, 0, 0)
        self.camera_name = raw_metadata.get("Core-Camera", None)

    def _get_camera_pixel_size(self) -> float | None:
        manager = CameraInfoManager()
        return manager.get_camera_pixel_size(self.camera_name)

    def _parse_dpc_channels(self) -> tuple[tuple, tuple, tuple]:
        channel_names: list[str] = self.dataset.summary_metadata.get("ChNames", [])
        dpc_channel_idxs = [i for i, name in enumerate(channel_names) if "DPC" in name]

        if not dpc_channel_idxs:
            user_input = simpledialog.askstring(
                "DPC Channel Selection",
                "Could not auto-detect DPC channels from metadata. "
                "Enter channel indices (comma separated, e.g. 0,1,2,3):",
            )
            if user_input:
                dpc_channel_idxs = [int(i) for i in user_input.split(",") if i.isdigit()]
            else:
                raise ValueError(
                    "No DPC channels specified; cannot proceed with processing."
                )

        dpc_rotations = tuple([
            channel_names[i].split("DPC_")[-1]
            for i in dpc_channel_idxs
            if "DPC_" in channel_names[i]
        ])

        if len(dpc_rotations) != len(dpc_channel_idxs):
            print("Could not auto-detect DPC channel rotations from metadata")
            dpc_rotations = None

        return tuple(channel_names), tuple(dpc_channel_idxs), dpc_rotations

    def _parse_axes_order_and_shape(self) -> tuple[tuple, tuple]:
        """
        Return axis order and corresponding sizes.
        The dataset's AxisOrder is reversed so that the slowest-changing
        axis comes first. y and x are appended last as they are always present.
        """
        axis_order: list[str] = []
        image_shape: list[int] = []

        for axis_key in reversed(self.dataset.summary_metadata["AxisOrder"]):
            axis_order.append(axis_key)
            image_shape.append(len(self.dataset.axes[axis_key]))

        axis_order.extend(["y", "x"])
        image_shape.extend([self.dataset.image_height, self.dataset.image_width])

        return tuple(axis_order), tuple(image_shape)

    def get_dpc_data(self) -> np.ndarray:
        """
        Load and return the DPC image data as a NumPy array.
        The array is sliced and transposed to match the expected order of the DPC solver.
        3D solver expects (Y, X, Z, channel), 2D solver expects (channel, Y, X).
        Note that currently the 3D solver can only handle a single time point and position. 
        Any additional axes are collapsed into a leading batch dimension and only the 
        first element is used. 2D solver can handle multiple time points and positions, 
        but they are also collapsed into a batch dimension.
        """
        p = self.dpc_parameters

        if p.solver_type == "2D":
            dpc_axes = ["channel", "y", "x"]
        else:
            dpc_axes = ["y", "x", "z", "channel"]

        # The dask array seems to not align with AxisOrder specified in the metadata
        # So define a fixed order here and then subset and transpose to match the solver's expected order.
        dask_array_axis_order = ["position", "time", "channel", "z", "y", "x"]

        other_axes = [ax for ax in dask_array_axis_order if ax not in dpc_axes]
        target_order = other_axes + dpc_axes
        transpose_order = [dask_array_axis_order.index(ax) for ax in target_order]

        reordered_slices = [p.image_axes_slices[p.image_axis_order.index(ax)]
                            for ax in dask_array_axis_order]

        # Subset the dask array before pulling data into RAM.
        raw = self.dataset.as_array()[*reordered_slices]

        data = np.asarray(raw)
        data = np.transpose(data, axes=transpose_order)

        if p.solver_type == "3D":
            # Collapse non-DPC axes into a single leading batch dimension,
            # then take only the first batch element. Since 3D solver currently 
            # only supports a single time point and position.
            # TODO: Implement method to store WOTFs and loop over 
            # any additional axes (time, position) for 3D solver.
            n_dpc_axes = len(dpc_axes)
            data = data.reshape(-1, *data.shape[-n_dpc_axes:])
            data = np.squeeze(data[0])
        elif p.solver_type == "2D":
            data = data.reshape(-1, data.shape[-2], data.shape[-1])

        return data

    def get_dpc_params(self) -> QDPCProcessingParameters:
        return self.dpc_parameters

    def update_dpc_params(self, new_params: QDPCProcessingParameters) -> None:
        self.dpc_parameters = new_params