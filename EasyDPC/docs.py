# =============================================================================
# qDPC NDTiff Processor - Documentation strings for GUI widgets
#
# Copyright (C) 2026 Ewan Drever-Smith
# Free to use, redistribute and modify under GPLv3, see LICENSE.md for details. 
# =============================================================================

"""
Documentation strings for the GUI widgets.
 Each entry is keyed by the parameter name used in DPCProcessingParameters
 and DPCParameterGUI. The values are displayed in the GUI docs side panel
 and highlighted when the user hovers over the corresponding form widget.
"""


DOCS: dict[str, str] = {
    "open_dir": (
        "Select the NDTiff dataset directory to process. The directory should contain"
        " TIFF files following the same name stem as the parent directory, e.g."
        "\n\nroot_dir/"
        "\n├── root_dir_NDTiffStack.tiff"
        "\n├── root_dir_NDTiffStack_1.tiff"
        "\n│   ..."
        "\n└── root_dir_NDTiffStack_N.tiff"
    ),
    "save_dir": (
        "Select the directory in which to save the processed output."
        " If left blank, output will be placed in subdirectories of the NDTiff directory(ies)."
        " Note that if multiple datasets are being processed, all outputs will be placed in the specified directory."
    ),
    "process_all": (
        "When checked, all NDTiff datasets found in the parent of the"
        " selected directory are processed sequentially using the same parameters. E.g."
        "\n\n../"
        "\n├── selected_dir/"
        "\n│     └── selected_dir_NDTiffStack.tiff"
        "\n├── other_dir_1/"
        "\n│     └── other_dir_1_NDTiffStack.tiff"
        "\n│   ..."
        "\n└── other_dir_N/"
        "\n      └── other_dir_N_NDTiffStack.tiff"
        "\n\nThe selected dataset is always processed first and is not repeated."
    ),
    "metadata": (
        "Metadata parsed from the input NDTiff file."
        "\nInput file: the path of the TIFF file being processed."
        "\nImage size: the dimensions of the image data as a list of integers."
        "\nAxis order: the corresponding axis labels, corresponding to the shape above"
        "\nChannel names: the names of each channel as parsed from the metadata."
        "\nZ-step: the axial step size in micrometres (um) parsed from the metadata, if available."
        "\nCamera: The name of the camera, if found. Used to look up the pixel size from the camera info manager."
    ),
    "slices": (
        "Python slice syntax to select a subset of frames along each axis before"
        " processing. E.g. ':' = all frames, '0:10' = frames 0-9, '5' = frame 5 only."
        " '0:20:2' = every second frame from 0 to 19."
    ),
    "wavelength": (
        "Illumination wavelength in micrometres (um)."
        "Defaults to 0.5 um (green light)."
    ),
    "na": (
        "Objective numerical aperture (NA)."
        " Determines the maximum spatial frequency that can be captured."
        " Check your objective specification sheet."
    ),
    "na_in": (
        "Inner NA of the DPC illumination pattern (non zero values indicate annular illumination)."
        " Should be <= objective NA. Set to 0 for a fully-filled aperture."
    ),
    "magnification": (
        "System magnification"
        " Used together with the camera pixel size to compute the effective"
        " pixel size in the sample plane."
    ),
    "camera_pixel_size": (
        "Physical pixel size of the camera sensor in micrometres (um)."
    ),
    "dpc_rotations": (
        "Comma-separated rotation angles (degrees) of the DPC half-circle/annulus"
        " illumination patterns, one per DPC channel."
        " if channel names contain 'DPC_ANGLE' (e.g. 'DPC_0', 'DPC_90', etc.) "
        " then rotations are parsed automatically from the metadata. "
        " Otherwise, the user must specify the rotations here in the same order as the DPC channels."
        " E.g. '0, 90, 180, 270' for ◓ ◑ ◒ ◐."
    ),
    "z_step": (
        "Axial step size between z-planes in micrometres (um)."
        " Required for 3D reconstruction only. Parsed automatically from the"
        " NDTiff metadata when available."
    ),
    "ri_medium": (
        "Refractive index of the sample medium."
        " Required for 3D reconstruction only."
    ),
    "solver": (
        "2D: reconstructs absorption and phase for each z-plane independently."
        "\n3D: jointly reconstructs the complex refractive index volume across"
        " all z-planes. Requires a z-stack and is significantly slower."
    ),
    "use_gpu": (
        "Offload 3D reconstruction computation to the GPU via CuPy."
        " Only available for the 3D solver. Requires ArrayFire."
    ),
    "reg_method": (
        "Regularisation method for the deconvolution."
        "\nTikhonov: fast L2 regularisation. Good default choice."
        "\nTV: Total Variation regularisation using Alternating Direction Method of Multipliers (ADMM)."
        " Slower but can reduce prevalence of aberrations."
    ),
    "tik_u": (
        "Tikhonov regularisation strength for the absorption channel (u)."
        " Typical range: 1e-5 to 1e-2."
    ),
    "tik_p": (
        "Tikhonov regularisation strength for the phase channel (p)."
        " Typical range: 1e-5 to 1e-2."
    ),
    "tau_u": (
        "TV regularisation parameter for the absorption channel."
        " Default value: 5e-5"
    ),
    "tau_p": (
        "TV regularisation parameter for the phase channel."
        " Default value: 5e-5"
    ),
    "rho": (
        "ADMM penalty parameter shared across channels."
        " Default value: 5e-5"
    ),
    "order": (
        "Number of times to apply fourier domain TV filter on the signals for each filtering operation"
        " Allowed values: 1(default), 2 or 3."
    ),
    "max_iter": (
        "number of ADMM iterations for solving this deconvolution problem with TV regularisation."
        " More iterations give a more converged result at the cost of runtime."
        " Typical range: 5 to 50."
    ),
    "bc_real": (
        "Boundary constraint on the real (phase) part of the refractive index (RI_real - n_medium)."
        " 'negative': phase <= RI_real_medium"
        " 'positive': phase >= RI_real_medium"
        " 3D TV solver only."
    ),
    "bc_imag": (
        "Boundary constraint on the imaginary (absorption) part of the refractive index."
        " 'negative': absorption <= RI_imag_medium (typically 0)"
        " 'positive': absorption >= RI_imag_medium (typically 0)"
        " 3D TV solver only."
    ),

}