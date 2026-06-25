# =============================================================================
# qDPC Processor
#
# Copyright (C) 2026 Ewan Drever-Smith
# Free to use, redistribute and modify under GPLv3, see LICENSE.md for details. 
# =============================================================================

"""
Wrapper for the 2D and 3D DPC algorithms made available by WallerLab
"""


from pathlib import Path

import numpy as np
import tifffile
import importlib

from .third_party.WallerLab.DPC_withAberrationCorrection.python_code.dpc_algorithm import DPCSolver

# Repository name is prefixed with a number, so use importlib to workaround the non-standard module name.
Solver3DDPC = importlib.import_module(
    ".third_party.WallerLab.3DQuantitativeDPC.python_code.algorithm_3ddpc",
    package=__package__
).Solver3DDPC

from .qdpc_processing_parameters import QDPCProcessingParameters


class QDPCProcessor:
    """Wraps the 2D and 3D DPC algorithms made available by WallerLab 
    and handles result saving."""

    def __init__(
        self, dpc_images: np.ndarray, params: QDPCProcessingParameters
    ) -> None:
        self.params = params
        self.dpc_images = dpc_images

    def _solve_2d(self, update_progress = None) -> np.ndarray:
        p = self.params
        effective_pixel_size = p.camera_pixel_size / p.magnification

        if update_progress is not None:
            update_progress(label="Calculating WOTFs and initializing 2D solver...")

        solver = DPCSolver(
            dpc_imgs=self.dpc_images,
            wavelength=p.wavelength,
            na=p.na,
            na_in=p.na_in,
            pixel_size=effective_pixel_size,
            rotation=p.dpc_rotations,
            dpc_num=len(p.dpc_channel_idxs),
        )
        if update_progress is not None:
            update_progress(label="2D solver initialised, setting regularisation parameters...")

        solver.setRegularizationParameters(
            reg_u=p.regularisation_params["Tikhonov"]["tik_u"],
            reg_p=p.regularisation_params["Tikhonov"]["tik_p"],
            tau_u=p.regularisation_params["TV"]["tau_u"],
            tau_p=p.regularisation_params["TV"]["tau_p"],
            rho=p.regularisation_params["TV"]["rho"],
        )

        if update_progress is not None:
            update_progress(label="Solving 2D qDPC reconstruction...")

        results = solver.solve(
            method=p.reg_method,
            tv_order=int(p.regularisation_params["TV"]["order"]),
            tv_max_iter=int(p.regularisation_params["TV"]["max_iter"]),
        )

        if update_progress is not None:
            update_progress(label="2D qDPC reconstruction complete, stacking results...")

        # Stack real (amplitude) and imaginary (phase) parts along a new axis.
        amplitude = np.stack([img.real for img in results], axis=0)
        phase = np.stack([img.imag for img in results], axis=0)
        return np.stack([amplitude, phase], axis=1)

    def _solve_3d(self, update_progress = None) -> np.ndarray:
        p = self.params
        effective_pixel_size = p.camera_pixel_size / p.magnification

        if update_progress is not None:
            update_progress(label="Calculating WOTFs and initializing 3D solver...")

        solver = Solver3DDPC(
            dpc_imgs=self.dpc_images,
            wavelength=p.wavelength,
            na=p.na,
            na_in=p.na_in,
            pixel_size=effective_pixel_size,
            rotation=p.dpc_rotations,
            pixel_size_z=p.z_step,
            RI_medium=p.ri_medium,
        )
        if update_progress is not None:
            update_progress(label="3D solver initialised, setting regularisation parameters...")

        solver.setRegularizationParameters(
            reg_real=p.regularisation_params["Tikhonov"]["tik_u"],
            reg_imag=p.regularisation_params["Tikhonov"]["tik_p"],
            tau=p.regularisation_params["TV"]["tau_p"],
            rho=p.regularisation_params["TV"]["rho"],
        )

        boundary_constraint = {
            "real": p.bc_real,
            "imag": p.bc_imag,
        }

        if update_progress is not None:
            update_progress(label="Solving 3D qDPC reconstruction...")
    
        refractive_index = solver.solve(
            p.reg_method,
            int(p.regularisation_params["TV"]["max_iter"]),
            boundary_constraint=boundary_constraint,
            use_gpu=p.use_gpu,
        )
        # Solver returns (Y, X, Z); transpose to (Z, Y, X) for standard ordering.
        return refractive_index.transpose(2, 0, 1)


    def _save_results(self, image: np.ndarray, output_path: Path) -> None:
        """
        Write passed image as a 32bit TIFF with a JSON parameter log.
        Appends an incrementing counter to the stem if the file already
        exists to avoid overwriting previous results.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        log_path = output_path.with_name(output_path.stem + "_log.json")
        original_stem = output_path.stem
        original_log_stem = log_path.stem

        counter = 1
        while output_path.exists():
            output_path = output_path.with_stem(f"{original_stem}_{counter}")
            log_path = log_path.with_stem(f"{original_log_stem}_{counter}")
            counter += 1

        # TODO: Embed processing metadata inside the TIFF file header.
        tifffile.imwrite(output_path, image.astype(np.float32))
        self.params.save_json(log_path)

    def process_and_save(self, output_path: Path | str | None = None, update_progress = None) -> None:
        """
        Run the qDPC algorithm and write results to output_path.
        If output_path is None, results are saved in a qDPC
        sub-directory of the input directory.
        """

        input_path = Path(self.params.input_file_path)
        if not output_path:
            output_path = input_path / "qDPC" / input_path.name
        else:
            output_path = Path(Path(output_path) / input_path.name)

        if self.params.solver_type == "2D":
            if update_progress is not None:
                update_progress(label="Running 2D qDPC solver...")
            result = self._solve_2d(update_progress=update_progress)
            self._save_results(result, output_path.with_name(str(input_path.stem) + "_2DqDPC.tif"))
        elif self.params.solver_type == "3D":
            if update_progress is not None:
                update_progress(label="Running 3D qDPC solver...")
            result = self._solve_3d(update_progress=update_progress)
            self._save_results(result, output_path.with_name(str(input_path.stem) + "_3DqDPC.tif"))
