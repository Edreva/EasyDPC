# =============================================================================
# qDPC NDTiff Processor - Parameter Dataclass
#
# Copyright (C) 2026 Ewan Drever-Smith
# Free to use, redistribute and modify under GPLv3, see LICENSE.md for details. 
# =============================================================================

"""
Data class to hold all parameters required for qDPC processing.
"""


import json
from pathlib import Path
from dataclasses import asdict, dataclass, field

from .slice_utils import slice_to_str


@dataclass
class QDPCProcessingParameters:
    """
    All parameters required for DPC processing.
    Combines file metadata parsed from an NDTiff input with
    user specified processing options set via the GUI.
    """

    # Metadata parsed from the input file.
    input_file_path: Path | str
    image_shape: list[int]
    image_axis_order: list[str]
    channel_names: list[str]
    camera_name: str

    # User-configurable processing parameters.
    dpc_channel_idxs: list[int]    # Indices of channels used for DPC.
    dpc_rotations: list[int]       # e.g. [0, 90, 180, 270] for ◓ ◑ ◒ ◐.
    camera_pixel_size: float = 0.0
    magnification: float = 0.0
    na: float = 0.0
    na_in: float = 0.0
    wavelength: float = 0.5        # µm
    solver_type: str = "2D"        # "2D" or "3D"
    z_step: float = 0.0            # µm; required for 3D processing only.
    ri_medium: float = 1.0         # Refractive index; required for 3D only.
    reg_method: str = "Tikhonov"   # "Tikhonov" or "TV"
    regularisation_params: dict = field(default_factory=lambda: {
        "Tikhonov": {"tik_u": 1e-4, "tik_p": 1e-4},
        "TV": {
            "tau_u": 1e-5, "tau_p": 1e-5, "rho": 1e-5,
            "order": 1, "max_iter": 5,
        },
    })
    # Boundary constraints, used only for 3D TV regularisation.
    bc_real: str = "negative"
    bc_imag: str = "negative"
    use_gpu: bool = False
    # Slice selection for subsetting the data before processing.
    image_axes_slices: list | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def save_json(self, filepath: Path | str) -> None:
        """
        Serialise parameters to a JSON log file.
        """
        original_slices = self.image_axes_slices
        original_path = self.input_file_path

        self.input_file_path = str(self.input_file_path)
        if self.image_axes_slices is not None:
            self.image_axes_slices = [slice_to_str(s) for s in self.image_axes_slices]

        with open(filepath, "w") as f:
            json.dump(self.to_dict(), f, indent=4)

        # Restore mutable fields after serialisation.
        self.input_file_path = original_path
        self.image_axes_slices = original_slices
