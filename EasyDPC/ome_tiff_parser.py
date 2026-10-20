# =============================================================================
# qDPC OME-TIFF Parser
#
# Copyright (C) 2026 Ewan Drever-Smith
# Free to use, redistribute and modify under GPLv3, see LICENSE.md for details.
# =============================================================================

"""
OME-TIFF (and generic multi-page TIFF) metadata parser and data accessor.

OME-TIFF files from arbitrary sources cannot be relied upon to describe their
dimensions correctly, or at all. Only the in-plane axes (Y, X and any RGB
samples axis) are taken from the TIFF structure itself; every other axis is
treated as unconfirmed. The user chooses which axis holds the DPC
illumination images (and which is z, for 3D), may reinterpret a flattened
stack with an explicit shape, and picks the DPC indices along the channel
axis. OME-XML, Micro-Manager and ImageJ metadata are only used to suggest
defaults.

The logical axis layout exposed to the rest of EasyDPC is

    [series] + stack axes + plane axes

- series: present only when the file holds several images of identical
  shape (e.g. multiple OME <Image>s, such as Micro-Manager positions).
- stack axes: the axes enumerating TIFF pages within one image. Their shape
  can be overridden by the user, which reinterprets the page order in
  C order (last axis changing fastest).
- plane axes: the axes within a single TIFF page, i.e. Y, X and optionally S.
"""


import math
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import tifffile

from .qdpc_processing_parameters import QDPCProcessingParameters
from .camera_info_manager import CameraInfoManager


TIFF_SUFFIXES = (".tif", ".tiff")
OME_SUFFIXES = (".ome.tif", ".ome.tiff")

# Human readable names for tifffile axis codes, used for display only.
AXIS_CODE_NAMES = {
    "T": "time", "C": "channel", "Z": "depth", "S": "RGB sample",
    "I": "unlabelled", "Q": "unlabelled", "R": "tile", "M": "mosaic",
    "P": "phase", "A": "angle", "E": "lambda", "H": "lifetime",
    "L": "exposure", "V": "event", "Y": "height", "X": "width",
    "series": "image series",
}

_LENGTH_TO_UM = {
    "m": 1e6, "cm": 1e4, "mm": 1e3, "µm": 1.0, "um": 1.0, "micron": 1.0,
    "nm": 1e-3, "pm": 1e-6, "Å": 1e-4,
}


def _local_name(tag: str) -> str:
    """Strip the XML namespace from a tag."""
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in element if _local_name(c.tag) == name]


def _descendants(element: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in element.iter() if _local_name(c.tag) == name]


def _positive_float(value) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _length_um(value, unit: str | None) -> float | None:
    """Convert an OME length (default unit µm) to µm."""
    value = _positive_float(value)
    factor = _LENGTH_TO_UM.get(unit or "µm")
    if value is None or factor is None:
        return None
    return value * factor


def evenly_spaced_rotations(n: int) -> tuple[int, ...]:
    return tuple(int(i * 360 / n) for i in range(n))


def rotations_from_names(names: list[str]) -> tuple | None:
    """Parse rotations from channel names of the form 'DPC_<angle>'."""
    rotations = []
    for name in names:
        if "DPC_" not in name:
            return None
        try:
            angle = float(name.split("DPC_")[-1])
        except ValueError:
            return None
        rotations.append(int(angle) if angle.is_integer() else angle)
    return tuple(rotations)


def is_tiff_file(path: Path) -> bool:
    return path.is_file() and path.name.lower().endswith(TIFF_SUFFIXES)


class OMETiffParser:
    """
    Parses an OME-TIFF (or any multi-page TIFF) and exposes the DPC data and
    parameters required for qDPC processing. Mirrors the NDTiffParser
    interface (get_dpc_params, get_dpc_data, update_dpc_params) and adds
    methods for the user to assign axis roles.
    """

    def __init__(
        self,
        ome_tiff_path: Path | str,
        existing_params: QDPCProcessingParameters | None = None,
    ) -> None:
        self.ome_tiff_path = Path(ome_tiff_path)
        if not is_tiff_file(self.ome_tiff_path):
            raise ValueError(
                f"'{self.ome_tiff_path.name}' is not a TIFF file. "
                "Select a single .ome.tif / .tif file."
            )
        # Human readable remarks about what could / could not be detected.
        self.notes: list[str] = []
        self._inspect_file()
        self._parse_metadata(existing_params)

    # ------------------------------------------------------------------
    # File structure
    # ------------------------------------------------------------------

    def _inspect_file(self) -> None:
        with tifffile.TiffFile(self.ome_tiff_path) as tif:
            if not tif.series:
                raise ValueError("No image data found in file.")
            first = tif.series[0]

            # Use every series that matches the first one as an extra axis.
            self._series_numbers = [
                i for i, s in enumerate(tif.series)
                if s.shape == first.shape and s.dtype == first.dtype and s.axes == first.axes
            ]
            if len(tif.series) > len(self._series_numbers):
                self.notes.append(
                    f"File contains {len(tif.series)} image series; only the "
                    f"{len(self._series_numbers)} matching the first series' shape are used."
                )

            axes, shape = first.axes, tuple(first.shape)
            if "Y" not in axes or "X" not in axes:
                raise ValueError(f"Could not locate the Y and X axes in the file (axes '{axes}').")

            # Axes stored within a single page (YX, YXS or SYX) are reliable.
            plane_shape = tuple(first.keyframe.shape)
            plane_ndim = len(plane_shape)
            plane_codes = axes[-plane_ndim:]
            if shape[-plane_ndim:] != plane_shape or "Y" not in plane_codes or "X" not in plane_codes:
                plane_ndim = len(axes) - min(axes.index("Y"), axes.index("X"))

            self._file_stack_shape = shape[:len(shape) - plane_ndim]
            self._file_stack_codes = tuple(axes[:len(shape) - plane_ndim])
            self._plane_shape = shape[len(shape) - plane_ndim:]
            self._plane_codes = tuple(axes[len(shape) - plane_ndim:])
            self._stack_shape = self._file_stack_shape
            self._stack_codes = self._file_stack_codes
            # Pages can be read selectively if each page is exactly one plane.
            self._pages_indexable = (
                math.prod(self._file_stack_shape) == len(first.pages)
                and self._plane_shape == plane_shape
            )
            self.dtype = first.dtype
            self._read_metadata(tif)

    @property
    def _has_series_axis(self) -> bool:
        return len(self._series_numbers) > 1

    def _logical_codes(self) -> tuple[str, ...]:
        series = ("series",) if self._has_series_axis else ()
        return series + self._stack_codes + self._plane_codes

    def _file_codes(self) -> tuple[str, ...]:
        series = ("series",) if self._has_series_axis else ()
        return series + self._file_stack_codes + self._plane_codes

    def _logical_shape(self) -> tuple[int, ...]:
        series = (len(self._series_numbers),) if self._has_series_axis else ()
        return series + tuple(self._stack_shape) + tuple(self._plane_shape)

    @property
    def planes_per_series(self) -> int:
        return math.prod(self._file_stack_shape)

    @property
    def file_stack_shape(self) -> tuple[int, ...]:
        return tuple(self._file_stack_shape)

    @property
    def stack_shape(self) -> tuple[int, ...]:
        return tuple(self._stack_shape)

    @property
    def is_reshaped(self) -> bool:
        return tuple(self._stack_shape) != tuple(self._file_stack_shape)

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def _read_metadata(self, tif: tifffile.TiffFile) -> None:
        self.channel_names: list[str] = []
        self.camera_name: str | None = None
        self.physical_pixel_size: float | None = None   # µm, sample plane
        self.z_step: float | None = None                # µm
        self.objective_magnification: float | None = None
        self.objective_na: float | None = None
        self.source_files: set[Path] = {self.ome_tiff_path.resolve()}

        if tif.is_ome:
            self.format_description = "OME-TIFF"
            try:
                self._read_ome_xml(tif.ome_metadata)
            except ET.ParseError as exc:
                self.notes.append(f"OME-XML could not be parsed ({exc}); it has been ignored.")
        elif tif.is_imagej:
            self.format_description = "ImageJ TIFF (no OME-XML)"
            self._read_imagej(tif)
        else:
            self.format_description = "TIFF (no OME-XML)"

        self._read_micromanager(tif)

    def _read_ome_xml(self, xml: str) -> None:
        root = ET.fromstring(xml)
        images = _children(root, "Image")
        if not images:
            return
        first_series = self._series_numbers[0]
        image = images[first_series] if first_series < len(images) else images[0]

        pixels = next(iter(_children(image, "Pixels")), None)
        if pixels is not None:
            self.physical_pixel_size = _length_um(
                pixels.get("PhysicalSizeX"), pixels.get("PhysicalSizeXUnit"))
            self.z_step = _length_um(
                pixels.get("PhysicalSizeZ"), pixels.get("PhysicalSizeZUnit"))
            names = [c.get("Name") or "" for c in _children(pixels, "Channel")]
            if any(names):
                self.channel_names = names

        # Objective: the one referenced by the image, or the only one present.
        objectives = _descendants(root, "Objective")
        settings = next(iter(_children(image, "ObjectiveSettings")), None)
        objective = None
        if settings is not None:
            objective = next((o for o in objectives if o.get("ID") == settings.get("ID")), None)
        if objective is None and len(objectives) == 1:
            objective = objectives[0]
        if objective is not None:
            self.objective_magnification = _positive_float(
                objective.get("NominalMagnification") or objective.get("CalibratedMagnification"))
            self.objective_na = _positive_float(objective.get("LensNA"))

        # Detector model, used as the key for the camera pixel size lookup.
        models = {d.get("Model") for d in _descendants(root, "Detector") if d.get("Model")}
        if len(models) == 1:
            self.camera_name = models.pop()

        # Multi-file OME-TIFF: note every file in the set, so that batch
        # processing does not process the same dataset once per file.
        for uuid in _descendants(root, "UUID"):
            if uuid.get("FileName"):
                self.source_files.add((self.ome_tiff_path.parent / uuid.get("FileName")).resolve())

    def _read_imagej(self, tif: tifffile.TiffFile) -> None:
        metadata = tif.imagej_metadata or {}
        if str(metadata.get("unit", "")).lower() in ("micron", "um", "µm", "\\u00B5m"):
            self.z_step = _positive_float(metadata.get("spacing"))
            try:
                numerator, denominator = tif.pages[0].tags["XResolution"].value
                self.physical_pixel_size = _positive_float(denominator / numerator)
            except (KeyError, ZeroDivisionError, TypeError, ValueError):
                pass

    def _read_micromanager(self, tif: tifffile.TiffFile) -> None:
        """Micro-Manager writes the same keys the NDTiff parser relies on."""
        try:
            summary = (tif.micromanager_metadata or {}).get("Summary") or {}
        except Exception:
            summary = {}
        try:
            page_metadata = tif.pages[0].tags["MicroManagerMetadata"].value
        except Exception:
            page_metadata = {}
        if not isinstance(page_metadata, dict):
            page_metadata = {}

        camera = page_metadata.get("Core-Camera") or summary.get("Core-Camera")
        if camera:
            # Prefer MM device names, so the camera pixel size cache is
            # shared with NDTiff datasets from the same microscope.
            self.camera_name = camera
        if not self.channel_names and summary.get("ChNames"):
            self.channel_names = list(summary["ChNames"])
        if self.z_step is None:
            self.z_step = _positive_float(summary.get("z-step_um"))

    def metadata_summary(self) -> list[tuple[str, str]]:
        """Extra (label, value) lines shown in the GUI metadata section."""
        codes = self._file_codes()
        shape = (len(self._series_numbers),) if self._has_series_axis else ()
        shape += self._file_stack_shape + self._plane_shape
        objective = []
        if self.objective_magnification:
            objective.append(f"{self.objective_magnification:g}x")
        if self.objective_na:
            objective.append(f"NA {self.objective_na:g}")
        return [
            ("Format", self.format_description),
            ("File axes", ", ".join(f"{c} ({n})" for c, n in zip(codes, shape))),
            ("Pixel size (µm)", f"{self.physical_pixel_size:g}" if self.physical_pixel_size else "N/A"),
            ("Objective", " / ".join(objective) if objective else "N/A"),
        ]

    # ------------------------------------------------------------------
    # Axis roles
    # ------------------------------------------------------------------

    def selectable_axes(self) -> list[int]:
        """Indices of axes that may be assigned as channel or z (all but Y/X)."""
        return [i for i, c in enumerate(self._logical_codes()) if c not in ("Y", "X")]

    def describe_axis(self, axis: int) -> str:
        code = self._logical_codes()[axis]
        name = AXIS_CODE_NAMES.get(code, code)
        if self.is_reshaped and axis in self._stack_axis_indices():
            name = "user-defined"
        return f"axis {axis}: {name} (size {self._logical_shape()[axis]})"

    def _stack_axis_indices(self) -> range:
        start = 1 if self._has_series_axis else 0
        return range(start, start + len(self._stack_shape))

    def axis_names(self, channel_axis: int | None, z_axis: int | None) -> tuple[str, ...]:
        """Names used for image_axis_order, reflecting the assigned roles."""
        codes = self._logical_codes()
        names = []
        for i, code in enumerate(codes):
            if i == channel_axis:
                names.append("channel")
            elif i == z_axis:
                names.append("z")
            elif code in ("Y", "X"):
                names.append(code.lower())
            elif code == "series":
                names.append("series")
            elif code == "T" and codes.count("T") == 1 and not self.is_reshaped:
                names.append("time")
            else:
                names.append(f"axis{i}")
        return tuple(names)

    def _validate_axis(self, axis: int | None, role: str) -> None:
        if axis is None:
            return
        if axis not in self.selectable_axes():
            raise ValueError(f"Axis {axis} cannot be used as the {role} axis.")

    def set_axis_roles(self, channel_axis: int | None, z_axis: int | None) -> None:
        """Assign which axes hold the DPC channels and z. Resets slices."""
        self._validate_axis(channel_axis, "channel")
        self._validate_axis(z_axis, "z")
        if channel_axis is not None and channel_axis == z_axis:
            raise ValueError("The channel axis and z axis must be different axes.")
        p = self.dpc_parameters
        p.channel_axis = channel_axis
        p.z_axis = z_axis
        p.image_axis_order = self.axis_names(channel_axis, z_axis)
        p.image_axes_slices = None

    def _apply_stack_shape(self, shape) -> None:
        shape = tuple(int(n) for n in shape) if shape else self._file_stack_shape
        if any(n < 1 for n in shape):
            raise ValueError("Stack shape entries must be positive integers.")
        if math.prod(shape) != self.planes_per_series:
            raise ValueError(
                f"Stack shape {' x '.join(map(str, shape))} = {math.prod(shape)} planes, "
                f"but the file holds {self.planes_per_series} planes"
                + (" per series." if self._has_series_axis else ".")
            )
        if shape == tuple(self._file_stack_shape):
            self._stack_shape, self._stack_codes = self._file_stack_shape, self._file_stack_codes
        else:
            self._stack_shape, self._stack_codes = shape, ("Q",) * len(shape)

    def set_stack_shape(self, shape) -> None:
        """
        Reinterpret the page stack with a new shape (C order, last axis
        fastest), e.g. a flat 60 page stack as (15, 4). Pass None to restore
        the file's own shape. Axis roles and slices are reset.
        """
        self._apply_stack_shape(shape)
        p = self.dpc_parameters
        p.stack_shape = list(self._stack_shape) if self.is_reshaped else None
        p.image_shape = self._logical_shape()
        p.channel_axis = p.z_axis = None
        p.image_axis_order = self.axis_names(None, None)
        p.image_axes_slices = None
        p.dpc_channel_idxs = ()

    def default_dpc_selection(self, channel_axis: int | None) -> tuple[tuple, tuple]:
        """Suggested DPC indices and rotations along *channel_axis*."""
        if channel_axis is None:
            return (), ()
        size = self._logical_shape()[channel_axis]
        names = self.channel_names_for_axis(channel_axis)
        idxs: tuple[int, ...] = ()
        if names:
            idxs = tuple(i for i, n in enumerate(names) if "DPC" in n.upper())
        if not idxs and size <= 8:
            # Without names, assume every image along a short axis is DPC.
            idxs = tuple(range(size))
        return idxs, self.rotations_for(idxs, channel_axis)

    def channel_names_for_axis(self, channel_axis: int | None) -> list[str] | None:
        """Channel names, only if they describe *channel_axis*."""
        if channel_axis is None or self.is_reshaped:
            return None
        codes, shape = self._logical_codes(), self._logical_shape()
        if codes[channel_axis] == "C" and len(self.channel_names) == shape[channel_axis]:
            return self.channel_names
        return None

    def rotations_for(self, idxs, channel_axis: int | None) -> tuple:
        if not idxs:
            return ()
        names = self.channel_names_for_axis(channel_axis)
        if names:
            rotations = rotations_from_names([names[i] for i in idxs])
            if rotations is not None:
                return rotations
        return evenly_spaced_rotations(len(idxs))

    def set_dpc_indices(self, idxs) -> None:
        p = self.dpc_parameters
        if p.channel_axis is None:
            raise ValueError("Select the DPC channel axis first.")
        size = self._logical_shape()[p.channel_axis]
        idxs = tuple(int(i) for i in idxs)
        if not idxs or any(not 0 <= i < size for i in idxs):
            raise ValueError(f"DPC indices must be within 0..{size - 1}.")
        p.dpc_channel_idxs = idxs

    # ------------------------------------------------------------------
    # Parameters
    # ------------------------------------------------------------------

    def _pixel_size_defaults(self) -> tuple[float, float]:
        """Best guess of (camera pixel size, magnification) from metadata."""
        camera_px = None
        if self.camera_name:
            camera_px = CameraInfoManager().get_camera_pixel_size(self.camera_name)
        magnification = self.objective_magnification
        sample_px = self.physical_pixel_size

        if camera_px and sample_px and not magnification:
            magnification = round(camera_px / sample_px, 3)
        elif not camera_px and sample_px:
            if magnification:
                camera_px = sample_px * magnification
            else:
                camera_px, magnification = sample_px, 1.0
                self.notes.append(
                    f"Only the sample-plane pixel size ({sample_px:g} µm) is known, so the camera "
                    "pixel size is set to it with magnification 1. Adjust both together if needed."
                )
        return camera_px or 0.0, magnification or 0.0

    def _parse_metadata(self, existing_params: QDPCProcessingParameters | None) -> None:
        if existing_params is not None:
            self._update_existing_params(existing_params)
            return

        codes = self._logical_codes()
        channel_axis = codes.index("C") if "C" in codes else None
        z_axis = codes.index("Z") if "Z" in codes else None
        if channel_axis is None:
            self.notes.append(
                "No channel axis found in the metadata: select the axis that holds the DPC images."
            )
        else:
            self.notes.append(
                "Channel axis suggested from file metadata: please confirm it and the DPC indices."
            )
        dpc_idxs, rotations = self.default_dpc_selection(channel_axis)
        camera_px, magnification = self._pixel_size_defaults()

        self.dpc_parameters = QDPCProcessingParameters(
            input_file_path=self.ome_tiff_path,
            image_shape=self._logical_shape(),
            image_axis_order=self.axis_names(channel_axis, z_axis),
            channel_names=tuple(self.channel_names),
            camera_name=self.camera_name,
            dpc_channel_idxs=dpc_idxs,
            dpc_rotations=rotations,
            camera_pixel_size=camera_px,
            magnification=magnification,
            na=self.objective_na or 0.0,
            z_step=self.z_step or 0.0,
            input_format="OME-TIFF",
            channel_axis=channel_axis,
            z_axis=z_axis,
            source_axes=list(self._file_codes()),
        )

    def _update_existing_params(self, p: QDPCProcessingParameters) -> None:
        """
        Batch mode: reuse the axis roles, DPC indices and all user-set values
        from a previous file, after checking the layout is compatible.
        """
        if p.source_axes is not None and list(p.source_axes) != list(self._file_codes()):
            raise ValueError(
                f"Axis layout ({', '.join(self._file_codes())}) differs from the first file "
                f"({', '.join(p.source_axes)}); process this file separately."
            )
        self._apply_stack_shape(p.stack_shape)
        shape = self._logical_shape()
        if p.channel_axis is not None and p.dpc_channel_idxs and \
                max(p.dpc_channel_idxs) >= shape[p.channel_axis]:
            raise ValueError(
                f"DPC indices {tuple(p.dpc_channel_idxs)} exceed the channel axis size "
                f"({shape[p.channel_axis]}) of this file."
            )
        p.input_file_path = self.ome_tiff_path
        p.image_shape = shape
        p.image_axis_order = self.axis_names(p.channel_axis, p.z_axis)
        p.channel_names = tuple(self.channel_names)
        p.camera_name = self.camera_name
        p.z_step = self.z_step or p.z_step
        self.dpc_parameters = p

    # ------------------------------------------------------------------
    # Data access
    # ------------------------------------------------------------------

    def get_dpc_data(self) -> np.ndarray:
        """
        Load and return the selected DPC images as a NumPy array, in the
        layout expected by the solvers (see NDTiffParser.get_dpc_data):
        2D -> (batch * n_dpc, Y, X), 3D -> (Y, X, Z, n_dpc).
        Only the TIFF pages needed for the selection are read from disk.
        """
        p = self.dpc_parameters
        codes, shape = self._logical_codes(), self._logical_shape()
        if p.channel_axis is None:
            raise ValueError("No DPC channel axis selected.")
        if not p.dpc_channel_idxs:
            raise ValueError("No DPC indices selected.")
        y_axis, x_axis = codes.index("Y"), codes.index("X")
        if p.solver_type == "3D":
            if p.z_axis is None:
                raise ValueError("The 3D solver needs a z axis: select one under Axis Assignment.")
            dpc_axes = [y_axis, x_axis, p.z_axis, p.channel_axis]
        else:
            dpc_axes = [p.channel_axis, y_axis, x_axis]

        slices = p.image_axes_slices
        if slices is None or len(slices) != len(shape):
            slices = [slice(None)] * len(shape)

        index_arrays = []
        for axis, size in enumerate(shape):
            if axis == p.channel_axis:
                idx = np.asarray(p.dpc_channel_idxs, dtype=int)
            else:
                idx = np.arange(size)[slices[axis]]
            if idx.size == 0:
                raise ValueError(f"The slice for axis '{p.image_axis_order[axis]}' selects no data.")
            index_arrays.append(idx)

        data = self._read_selection(index_arrays)

        other_axes = [a for a in range(len(shape)) if a not in dpc_axes]
        data = np.transpose(data, other_axes + dpc_axes)

        if p.solver_type == "3D":
            # As for NDTiff, the 3D solver handles a single volume only.
            batch = data.reshape(-1, *data.shape[-4:])
            if batch.shape[0] > 1:
                print(f"3D solver processes one volume; using the first of {batch.shape[0]}.")
            return batch[0]
        return data.reshape(-1, data.shape[-2], data.shape[-1])

    def _read_selection(self, index_arrays: list[np.ndarray]) -> np.ndarray:
        """Read the outer product of per-axis index arrays, in logical axis order."""
        n_series_axes = 1 if self._has_series_axis else 0
        n_stack = len(self._stack_shape)
        series_sel = index_arrays[0] if n_series_axes else np.array([0])
        stack_sel = index_arrays[n_series_axes:n_series_axes + n_stack]
        plane_sel = index_arrays[n_series_axes + n_stack:]

        if n_stack:
            grids = np.meshgrid(*stack_sel, indexing="ij")
            pages = np.ravel_multi_index(grids, self._stack_shape).ravel()
        else:
            pages = np.array([0])

        blocks = []
        with tifffile.TiffFile(self.ome_tiff_path) as tif:
            for s in series_sel:
                block = self._read_pages(tif, self._series_numbers[s], pages)
                block = block.reshape(*[len(a) for a in stack_sel], *self._plane_shape)
                for offset, sel in enumerate(plane_sel):
                    block = np.take(block, sel, axis=n_stack + offset)
                blocks.append(block)
        return np.stack(blocks) if n_series_axes else blocks[0]

    def _read_pages(self, tif: tifffile.TiffFile, series_number: int, pages: np.ndarray) -> np.ndarray:
        """Return the requested planes of one series as (n_pages, *plane_shape)."""
        if self._pages_indexable:
            try:
                data = tif.asarray(key=pages.tolist(), series=series_number)
                return data.reshape(len(pages), *self._plane_shape)
            except Exception as exc:  # e.g. missing pages in a multi-file set
                print(f"Page-wise read failed ({exc}); reading the full series instead.")
        try:
            full = tifffile.memmap(self.ome_tiff_path, series=series_number, mode="r")
        except Exception:
            full = tif.series[series_number].asarray()
        full = full.reshape(-1, *self._plane_shape)
        return np.asarray(full[pages])

    def get_dpc_params(self) -> QDPCProcessingParameters:
        return self.dpc_parameters

    def update_dpc_params(self, new_params: QDPCProcessingParameters) -> None:
        self.dpc_parameters = new_params
