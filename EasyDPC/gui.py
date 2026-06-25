# =============================================================================
# qDPC NDTiff Processor - GUI
#
# Copyright (C) 2026 Ewan Drever-Smith
# Free to use, redistribute and modify under GPLv3, see LICENSE.md for details. 
# =============================================================================

"""
Graphical User Interface for qDPC Processor.
"""

from pathlib import Path
import threading

import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk

from .docs import DOCS
from .slice_utils import str_to_slice
from .qdpc_processing_parameters import QDPCProcessingParameters
from .qdpc_processor import QDPCProcessor
from .ndtiff_parser import NDTiffParser


class QDPCProcessorGUI:
    """GUI for selecting an NDTiff directory and adjusting DPC processing
    parameters before the solver is invoked.

    The directory picker row is shown immediately on open. The rest of
    the form is revealed only after a valid directory has been selected
    and its metadata successfully parsed.
    TODO: Allow for pixel binning in addition to current X/Y subsampling via slice entries
    """

    INITIAL_SIZE = (500, 200)
    EXPANDED_HEIGHT = 900
    DOCS_WIDTH = 280
    MAIN_FRAME_PADX = 10
    DOC_HIGHLIGHT_COLOR = ("gray75", "gray30")

    def __init__(self) -> None:
        self.params: QDPCProcessingParameters | None = None

        self.root = ctk.CTk()
        self.root.title("EasyDPC - qDPC NDTiff Processor")

        self.arrayfire_installed = True
        try:
            import arrayfire
        except ImportError:
            self.arrayfire_installed = False

        self.labels = {
            "open_dir":             "Input (NDTiff) Directory",
            "save_dir":             "Output Directory",
            "process_all":          "Process all NDTiff in parent directory?",
            "metadata":             "Detected Metadata",
            "slices":               "Axis Slices",
            "wavelength":           "Wavelength (µm)",
            "na":                   "Numerical Aperture (NA)",
            "na_in":                "Inner NA",
            "magnification":        "Magnification",
            "camera_pixel_size":    "Camera Pixel Size (µm)",
            "dpc_rotations":        "Source Rotations (degrees)",
            "z_step":               "Z-step (µm) [3D only]",
            "ri_medium":            "RI (Medium) [3D only]",
            "solver":               "Solver",
            "use_gpu":              "Use GPU [3D only]",
            "reg_method":           "Regularisation Method",
            "tik_u":                "tik_u",
            "tik_p":                "tik_p",
            "tau_u":                "tau_u",
            "tau_p":                "tau_p",
            "rho":                  "rho",
            "order":                "order",
            "max_iter":             "max_iter",
            "bc_real":              "BC (real)",
            "bc_imag":              "BC (imag)",
        }

        launch_position = (0, 10)
        self.root.geometry(f"{self.INITIAL_SIZE[0]}x{self.INITIAL_SIZE[1]}+{launch_position[0]}+{launch_position[1]}")
        self.root.minsize(self.INITIAL_SIZE[0], 200)

        self.entries: dict[str, ctk.CTkEntry] = {}
        self._build_widgets()

    def _build_widgets(self) -> None:
        self._main = ctk.CTkScrollableFrame(self.root)
        self._main.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=self.MAIN_FRAME_PADX, pady=10)
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        self._main.grid_columnconfigure(0, weight=1)
        self._main.grid_columnconfigure(1, weight=1)


        header_frame = ctk.CTkFrame(self._main, fg_color="transparent")
        header_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
        header_frame.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(
            header_frame, text="EasyDPC", font=ctk.CTkFont(size=28, weight="bold")
        ).grid(row=0, column=0, sticky=tk.EW)

        self._docs_open = False
        self._docs_button = ctk.CTkButton(
            header_frame, text="Docs ▸", width=70,
            command=self._toggle_docs,
        )
        self._docs_button.grid(row=0, column=1, sticky=tk.E)

        self._build_directory_row(self._main, row=1, key="open_dir")
        # Remaining sections are built and revealed in _on_directory_selected().
        self.root.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _toggle_docs(self) -> None:
        """Show or hide the documentation side panel."""
        # TODO: Improve consistency of resize, retaining 
        # user-adjusted window width when toggling the docs panel.
        if self._docs_open:
            self.root.minsize(self.INITIAL_SIZE[0], 200)
            self.root.geometry(f"{self.INITIAL_SIZE[0]}x{self.EXPANDED_HEIGHT}")
            self._docs_panel.grid_remove()
            self._docs_button.configure(text="Docs ▸")
            self._docs_open = False
        else:
            self.root.minsize(self.INITIAL_SIZE[0] + self.DOCS_WIDTH + 3 * self.MAIN_FRAME_PADX, 200)
            self.root.geometry(f"{self.INITIAL_SIZE[0] + self.DOCS_WIDTH + 3 * self.MAIN_FRAME_PADX}x{self.EXPANDED_HEIGHT}")
            if not hasattr(self, '_docs_panel'):
                self._build_docs_panel()
            self._docs_panel.grid()
            self._docs_button.configure(text="Docs ◂")
            self._docs_open = True

    
    def _build_docs_panel(self) -> None:
        """
        Build the documentation side panel (created once, then shown/hidden).
        Each entry is placed inside a CTkFrame so it can be highlighted
        independently when the user hovers over the corresponding form widget.
        References to those frames are stored in self._doc_frames keyed by
        the same parameter key used in DOCS.
        """
        self._docs_panel = ctk.CTkScrollableFrame(self.root, width=self.DOCS_WIDTH)   
        self._docs_panel.grid(
            row=0, column=1, sticky=(tk.N, tk.S, tk.E, tk.W), padx=(0, self.MAIN_FRAME_PADX), pady=10
        )
        self._doc_frames: dict[str, ctk.CTkFrame] = {}
        self._highlighted_key: str | None = None
 
        ctk.CTkLabel(
            self._docs_panel,
            text="Parameter Reference",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, pady=10, sticky=tk.EW)
 
        for i, (key, title) in enumerate(self.labels.items()):
            frame = ctk.CTkFrame(self._docs_panel, fg_color="transparent", corner_radius=6)
            frame.grid(row=i + 1, column=0, sticky=(tk.W, tk.E), pady=2)
            frame.grid_columnconfigure(0, weight=1)
            self._doc_frames[key] = frame
 
            ctk.CTkLabel(
                frame,
                text=title if title else key,
                font=ctk.CTkFont(size=12, weight="bold"),
                anchor="w",
            ).grid(row=0, column=0, sticky=tk.W, padx=6, pady=(6, 1))
            ctk.CTkLabel(
                frame,
                text=DOCS[key],
                wraplength=self.DOCS_WIDTH - self.MAIN_FRAME_PADX,
                justify=tk.LEFT,
                anchor="w",
            ).grid(row=1, column=0, sticky=tk.W, padx=self.MAIN_FRAME_PADX, pady=(0, 6))

    def _bind_hover(self, widget: tk.BaseWidget, doc_key: str) -> None:
        """ 
        Recursively bind hover Enter and Leave events to highlight and
        clear functions for the passed widget and all its children.
        """

        widget.bind("<Enter>", lambda _e, k=doc_key: self._hover_doc(k), add="+")
        widget.bind("<Leave>", lambda _e: self._clear_doc(), add="+")
        for child in widget.winfo_children():
            self._bind_hover(child, doc_key)

    def _hover_doc(self, key: str) -> None:
        """
        Highlight the docs entry corresponding to 'key' 
        and move it into view.
        """

        if not self._docs_open or not hasattr(self, '_doc_frames'):
            return
        if key not in self._doc_frames:
            return

        # Highlight the frame
        self._highlighted_key = key
        frame_to_highlight = self._doc_frames[key]
        frame_to_highlight.configure(fg_color=self.DOC_HIGHLIGHT_COLOR)

        # Scroll the docs panel so the highlighted entry is visible.
        panel_height = self._docs_panel.winfo_height()
        frame_y_pos = frame_to_highlight.winfo_y()
        self._docs_panel._parent_canvas.yview_moveto(frame_y_pos / panel_height)

    def _clear_doc(self) -> None:
        """Remove the highlight from the currently highlighted docs entry."""
        if not hasattr(self, '_doc_frames') or self._highlighted_key is None:
            return
        frame = self._doc_frames.get(self._highlighted_key)
        if frame:
            frame.configure(fg_color="transparent")

    def _build_directory_row(self, parent: ctk.CTkScrollableFrame, row: int, key: str, default: str | None = None) -> None:

        dir_frame = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(
            dir_frame, text=self.labels[key], font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, sticky=tk.W, pady=(10, 5))

        dir_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5))
        dir_frame.grid_columnconfigure(0, weight=1)

        path_entry = ctk.CTkEntry(dir_frame, width=200)
        path_entry.grid(row=1, column=0, sticky=(tk.W, tk.E), padx=(0, 6))
        self._bind_hover(path_entry, doc_key=key)
        self.entries[key] = path_entry

        if default:
            path_entry.insert(0, default)

        browse_button = ctk.CTkButton(
            dir_frame, text="Browse…", width=90, command=lambda: self._on_browse(key)
        )
        browse_button.grid(row=1, column=1)
        self._bind_hover(browse_button, doc_key=key)

        if key == "open_dir":
            # Placeholder for status message shown while parsing metadata.
            self._status_label = ctk.CTkLabel(parent, text="")
            self._status_label.grid(row=row + 1, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))

        self._form_start_row = row + 1
 
        return row + 1

    def _separator(self, parent: ctk.CTkFrame, row: int) -> int:
        sep = ctk.CTkFrame(parent, height=2, fg_color="gray50")
        sep.grid(row=row, column=0, columnspan=2, sticky="ew", pady=5)
        return row + 1

    def _section_label(self, parent: ctk.CTkFrame, row: int, text: str) -> int:
        ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=row, column=0, columnspan=2, pady=(0, 5), sticky=tk.EW
        )
        return row + 1
    
    def _build_labelled_entry(self, parent: ctk.CTkFrame, row: int, label_text: str,
                              entry_key: str, default_value: str | float, doc_key: str | None = None) -> int:
        ctk.CTkLabel(parent, text=label_text).grid(row=row, column=0, sticky=tk.W, pady=2)
        entry = ctk.CTkEntry(parent, width=150)
        entry.insert(0, str(default_value))
        entry.grid(row=row, column=1, sticky=tk.EW, pady=2)
        doc_key = doc_key if doc_key is not None else entry_key
        self._bind_hover(entry, doc_key=doc_key)
        self.entries[entry_key] = entry

        return row + 1

    def _on_browse(self, entry_key: str) -> None:
        directory = filedialog.askdirectory(title="Select NDTiff Directory")
        if directory:
            self.entries[entry_key].delete(0, tk.END)
            self.entries[entry_key].insert(0, directory)
            self._on_directory_selected(directory)

    def _on_directory_selected(self, path: str) -> None:
        """Parse metadata from *path* and reveal the parameter form."""
        self._status_label.configure(text="Parsing metadata...")
        self.root.update_idletasks()
        try:
            parser = NDTiffParser(path)
            self.params = parser.get_dpc_params()
            self._parser = parser
        except Exception as exc:
            self._status_label.configure(text=f"Error: {exc}")
            return
        self._status_label.configure(text="")
        self._build_form()
    
    def _build_credit_frame(self, parent: ctk.CTkFrame, row: int) -> int:
        wraplength = 0.9 * self.INITIAL_SIZE[0]
        ref_title_label = ctk.CTkLabel(parent, font=ctk.CTkFont(size=10, weight="bold"), justify=ctk.LEFT, text="References")
        self.ref_label = ctk.CTkLabel(parent, font=ctk.CTkFont(size=8, slant="italic"), justify=ctk.LEFT, wraplength=wraplength, text="")

        self.ref_text_3D = "Chen, M., Tian, L., & Waller, L. (2016). 3D differential " \
                            "phase contrast microscopy. Biomedical Optics Express, 7, 3940–3950."
        self.ref_text_2D_TV = "Chen, M., Phillips, Z. F., & Waller, L. (2018). Quantitative " \
                               "differential phase contrast (DPC) microscopy with computational " \
                               "aberration correction. Optics Express, 26, 32888."
        self.ref_text_2D_tik = "Tian, L., & Waller, L. (2015). Quantitative differential " \
                                "phase contrast imaging in an LED array microscope. Optics Express, 23, 11394."

        ref_title_label.grid(row=row, column=0, columnspan=2, pady=(5, 0), sticky=tk.SW)
        row += 1
        self.ref_label.grid(row=row, column=0, columnspan=2, pady=(0, 0), sticky=tk.NW)
        row += 1
        copyright_label = ctk.CTkLabel(parent, font=ctk.CTkFont(size=8, weight="bold"), text="Copyright (C) 2026 Ewan Drever-Smith")
        copyright_label.grid(row=row, column=0, columnspan=2)

        return row + 1


    def _build_form(self) -> None:
        """
        Build and display the parameter form below the directory row.
        """

        # If the form has been built before (e.g. the user changed directory),
        # all previously created form widgets are destroyed first.
        if hasattr(self, '_form_frame'):
            self._form_frame.destroy()
            self.entries.clear()

        self._form_frame = ctk.CTkFrame(self._main)
        self._form_frame.grid(
            row=self._form_start_row, column=0, columnspan=2, sticky=(tk.W, tk.E)
        )
        self._form_frame.grid_columnconfigure(0, weight=1)
        self._form_frame.grid_columnconfigure(1, weight=2)

        row = 0
        row = self._build_process_all_section(self._form_frame, row)
        row = self._build_directory_row(self._form_frame, row, key='save_dir', 
                                        default="")
        row = self._separator(self._form_frame, row=row)
        row = self._build_metadata_section(self._form_frame, row)
        row = self._build_slice_section(self._form_frame, row)
        row = self._build_system_params_section(self._form_frame, row)
        row = self._build_deconv_params_section(self._form_frame, row)
        row = self._build_buttons(self._form_frame, row)
        row = self._build_progress_bar(self._form_frame, row)
        row = self._build_credit_frame(self._form_frame, row)

        self._set_3d_params_enabled(self.solver_var.get() == "3D")
        self._set_reg_method(self.params.reg_method)

        self.root.geometry(f"{self.root.winfo_reqwidth()}x{self.EXPANDED_HEIGHT}")

    def _build_metadata_section(self, parent: ctk.CTkFrame, row: int) -> int:
        row = self._section_label(parent, row, self.labels["metadata"])

        labels = [
            ("Input file", Path(self.params.input_file_path).name),
            ("Image size", " x ".join(str(s) for s in self.params.image_shape)),
            ("Axis order", ", ".join(str(a) for a in self.params.image_axis_order)),
            ("Channels", ", ".join(str(c) for c in self.params.channel_names) 
             if self.params.channel_names else "N/A"),
            ("Z-step (µm)", self.params.z_step if self.params.z_step else "N/A"),
            ("Camera", self.params.camera_name if self.params.camera_name else "N/A"),
        ]

        for label, value in labels:
            label_label = ctk.CTkLabel(parent, text=f"{label}:", 
                                       justify=tk.LEFT, font=ctk.CTkFont(weight="bold"))
            label_label.grid(row=row, column=0, columnspan=2, pady=0, sticky=tk.W)
            value_label = ctk.CTkLabel(parent, text=value, justify=tk.LEFT)
            value_label.grid(row=row, column=1, columnspan=2, pady=0, sticky=tk.W)
            self._bind_hover(label_label, doc_key="metadata")
            self._bind_hover(value_label, doc_key="metadata")

            row += 1

        return row + 1

    def _build_process_all_section(self, parent: ctk.CTkFrame, row: int) -> int:
        self.process_all_var = tk.BooleanVar(value=False)
        process_all_cb = ctk.CTkCheckBox(
            parent,
            text=self.labels["process_all"],
            variable=self.process_all_var,
        )
        process_all_cb.grid(row=row, columnspan=2, column=0, sticky=tk.W)
        self._bind_hover(process_all_cb, "process_all")
        return row + 1

    def _build_slice_section(self, parent: ctk.CTkFrame, row: int) -> int:
        row = self._separator(parent, row)
        row = self._section_label(parent, row, self.labels["slices"])

        for i, axis in enumerate(self.params.image_axis_order):
            if axis == "channel" or self.params.image_shape[i] <= 1:
                # DPC channels identified elsewhere.
                continue
            label = f"{axis} (size {self.params.image_shape[i]}):"
            default = ":"
            entry_key = f"{axis}_slice"
            row = self._build_labelled_entry(parent, row, label, entry_key, default, doc_key="slices")

        return row

    def _build_system_params_section(self, parent: ctk.CTkFrame, row: int) -> int:
        row = self._separator(parent, row)
        row = self._section_label(parent, row, "System Parameters")

        system_params = [
            ("wavelength", self.params.wavelength),
            ("na", self.params.na),
            ("na_in", self.params.na_in),
            ("magnification", self.params.magnification),
            ("camera_pixel_size", self.params.camera_pixel_size),
            ("dpc_rotations", ", ".join(str(r) for r in self.params.dpc_rotations)),
            ("z_step", self.params.z_step),
            ("ri_medium", self.params.ri_medium),
        ]

        for key, default in system_params:
            label = f"{self.labels.get(key, key)}:"
            row = self._build_labelled_entry(parent, row, label, key, default)

        return row

    def _build_deconv_params_section(self, parent: ctk.CTkFrame, row: int) -> int:
        row = self._separator(parent, row)
        row = self._section_label(parent, row, "Deconvolution Parameters")

        # Solver type (2D / 3D).
        ctk.CTkLabel(parent, text=f"{self.labels['solver']}:").grid(row=row, column=0, sticky=tk.W, pady=2)
        solver_frame = ctk.CTkFrame(parent, fg_color="transparent")
        solver_frame.grid(row=row, column=1, sticky=tk.EW)
        self.solver_var = tk.StringVar(value="3D" if self.params.z_step > 0 else "2D")
        ctk.CTkRadioButton(
            solver_frame, text="2D", variable=self.solver_var, value="2D",
            command=lambda: self._set_3d_params_enabled(False),
        ).grid(row=0, column=0, padx=5, sticky=tk.EW)
        ctk.CTkRadioButton(
            solver_frame, text="3D", variable=self.solver_var, value="3D",
            command=lambda: self._set_3d_params_enabled(True),
        ).grid(row=0, column=1, padx=5, sticky=tk.EW)
        self._bind_hover(solver_frame, "solver")
        row += 1

        # GPU acceleration (3D only).
        ctk.CTkLabel(parent, text=f"{self.labels['use_gpu']}:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.use_gpu_var = tk.BooleanVar(value=self.params.use_gpu)
        self.use_gpu_checkbutton = ctk.CTkCheckBox(parent, text="", variable=self.use_gpu_var)
        self.use_gpu_checkbutton.grid(row=row, column=1, sticky=tk.W, padx=(4, 0), pady=2)
        if not self.arrayfire_installed:
            self.use_gpu_checkbutton.configure(state=tk.DISABLED)
            self.use_gpu_checkbutton.configure(text="(ArrayFire not installed)")
            self.use_gpu_var.set(False)
        self._bind_hover(self.use_gpu_checkbutton, "use_gpu")
        row += 1

        # Regularisation method.
        ctk.CTkLabel(parent, text=f"{self.labels['reg_method']}:").grid(row=row, column=0, sticky=tk.W, pady=2)
        method_frame = ctk.CTkFrame(parent, fg_color="transparent")
        method_frame.grid(row=row, column=1, sticky=tk.EW, pady=2)
        self.method_var = tk.StringVar(value=self.params.reg_method)
        ctk.CTkRadioButton(
            method_frame, text="Tikhonov", variable=self.method_var, value="Tikhonov",
            command=lambda: self._set_reg_method("Tikhonov"),
        ).grid(row=0, column=0, padx=5, sticky=tk.EW)
        ctk.CTkRadioButton(
            method_frame, text="TV", variable=self.method_var, value="TV",
            command=lambda: self._set_reg_method("TV"),
        ).grid(row=0, column=1, padx=5, sticky=tk.EW)
        self._bind_hover(method_frame, "reg_method")
        row += 1

        # Regularisation parameter sub-panels, one per method.
        self.reg_param_frames: dict[str, ctk.CTkFrame] = {}
        last_row_index = 0

        for method, method_params in self.params.regularisation_params.items():
            frame = ctk.CTkFrame(parent, fg_color="transparent")
            frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=5)
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_columnconfigure(1, weight=2)
            frame.grid_columnconfigure(2, weight=1)
            frame.grid_columnconfigure(3, weight=2)

            self.reg_param_frames[method] = frame

            for i, (key, value) in enumerate(method_params.items()):
                col_offset = (i % 2) * 2
                ctk.CTkLabel(frame, text=f"{key}:").grid(
                    row=i // 2, column=col_offset, sticky=tk.W, padx=(10,2),pady=2
                )
                entry = ctk.CTkEntry(frame)
                entry.grid(row=i // 2, column=col_offset + 1, sticky=tk.EW, padx=(0,20), pady=2)
                entry.insert(0, str(value))
                self._bind_hover(entry, doc_key=key)
                self.entries[key] = entry
                last_row_index = i // 2

        # Boundary constraints are shown inside the TV sub-panel.
        bc_row = last_row_index + 1
        tv_frame = self.reg_param_frames["TV"]

        ctk.CTkLabel(tv_frame, text=self.labels["bc_real"]).grid(row=bc_row, column=0, sticky=tk.W, padx=(10,0), pady=2)
        self.real_bc_combobox = ctk.CTkComboBox(
            tv_frame, values=["negative", "positive"],
        )
        self.real_bc_combobox.grid(row=bc_row, column=1, sticky=tk.EW, padx=(0,20), pady=2)
        self.real_bc_combobox.set(self.params.bc_real)
        self._bind_hover(self.real_bc_combobox, "bc_real")

        ctk.CTkLabel(tv_frame, text=self.labels["bc_imag"]).grid(row=bc_row, column=2, sticky=tk.W, padx=(10,0), pady=2)
        self.imag_bc_combobox = ctk.CTkComboBox(
            tv_frame, values=["negative", "positive"],
        )
        self.imag_bc_combobox.grid(row=bc_row, column=3, sticky=tk.EW, padx=(0,20), pady=2)
        self.imag_bc_combobox.set(self.params.bc_imag)
        self._bind_hover(self.imag_bc_combobox, "bc_imag")

        return row + 1

    def _build_buttons(self, parent: ctk.CTkFrame, row: int) -> int:
        button_frame = ctk.CTkFrame(parent, fg_color="transparent")
        button_frame.grid(row=row, column=0, columnspan=2, pady=(10,0))
        ctk.CTkButton(button_frame, text="Process", command=self._on_process).pack(
            side=tk.LEFT, padx=5
        )
        ctk.CTkButton(button_frame, text="Cancel", command=self._on_cancel,
                      fg_color="gray40", hover_color="gray30").pack(
            side=tk.LEFT, padx=5
        )
        return row + 1 

    def _build_progress_bar(self, parent: ctk.CTkFrame, row: int) -> int:
        # While using WallerLab algorithms as is, no progress feedback,
        # so set progression to be indeterminate

        self.progress_bar = ctk.CTkProgressBar(parent, mode='indeterminate')
        self.progress_bar.grid(row=row, column=0, columnspan=2, pady=(10, 0), sticky=tk.EW)
        row += 1
        self.progress_label_filename = ctk.CTkLabel(parent, text="")
        self.progress_label_filename.grid(row=row, column=0, columnspan=2)
        row += 1
        self.progress_label = ctk.CTkLabel(parent, text="")
        self.progress_label.grid(row=row, column=0, columnspan=2, pady=0)

        # Add to grid so its position is set, can grid() later to show
        self.progress_label.grid_remove()
        self.progress_label_filename.grid_remove()
        self.progress_bar.grid_remove() 

        return row + 1

    def _start_progress_bar(self, file_label: str | None = None, progress_label: str | None = None, speed: int = 1):
        self.progress_label.grid()
        self.progress_label_filename.grid()
        self.progress_bar.grid()
        self.progress_bar.configure(indeterminate_speed=speed, determinate_speed=speed)
        self.update_progress_callback(file_label, progress_label)
        self.progress_bar.start()

    def _end_progress_bar(self, label: str):
        self.progress_label.configure(text=label)
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(1)


    def update_progress_callback(self, file_label: str | None = None, label: str | None = None, fraction: float | None = None) -> None:
        if file_label is not None:
            self.progress_label_filename.configure(text=f"File: {file_label}")
        if label is not None:
            self.progress_label.configure(text=label)
        if fraction is not None:
            self.progress_bar.set(fraction)

    def _set_3d_params_enabled(self, enabled: bool) -> None:
        """Enable or disable widgets that are only relevant for 3D solving."""
        for key in ("z_step", "ri_medium"):
            if key in self.entries:
                self.entries[key].grid_remove() if not enabled else self.entries[key].grid()
        self.real_bc_combobox.grid_remove() if not enabled else self.real_bc_combobox.grid()
        self.imag_bc_combobox.grid_remove() if not enabled else self.imag_bc_combobox.grid()
        
        self.use_gpu_checkbutton.grid_remove() if not enabled else self.use_gpu_checkbutton.grid()

        self._update_ref_label()

    def _update_ref_label(self) -> None:
        if self.solver_var.get() == "3D":
            self.ref_label.configure(text=f"{self.ref_text_3D}")
        else:
            ref = self.ref_text_2D_TV if self.method_var.get() == "TV" else self.ref_text_2D_tik
            self.ref_label.configure(text=f"{ref}")

    def _set_reg_method(self, method: str) -> None:
        """Show the parameter sub-panel for *method* and hide all others."""
        for name, frame in self.reg_param_frames.items():
            if name == method:
                frame.grid()
            else:
                frame.grid_remove()
        self._update_ref_label()

    def _parse_axis_slices(self) -> list[slice]:
        """
        Read axis slice strings from the GUI entries and return
        a list of slice objects in axis order.

        Falls back to slice(None) for each axis on parse failure.
        """
        slices: list[slice] = []
        for axis in self.params.image_axis_order:
            if axis == "channel":
                idxs = self.params.dpc_channel_idxs
                slices.append(slice(idxs[0], idxs[-1] + 1))
                continue
            entry = self.entries.get(f"{axis}_slice")
            if entry is None:
                slices.append(slice(None))
                continue
            try:
                slices.append(str_to_slice(entry.get()))
            except Exception as exc:
                messagebox.showerror(
                    "Invalid Slice",
                    f"Invalid slice syntax for axis '{axis}': {exc}",
                )
                return [slice(None)] * len(self.params.image_axis_order)
        return slices
    
    def process(self) -> None:
        data_dir = str(self.params.input_file_path)
        save_dir = str(self.entries['save_dir'].get())

        try:
            process_all = self.process_all_var.get() if hasattr(self, 'process_all_var') else False

            self._start_progress_bar(file_label=str(Path(data_dir).name), progress_label="Starting Processing...")
            processor = QDPCProcessor(self._parser.get_dpc_data(), self.params)
            processor.process_and_save(output_path=save_dir,
                                       update_progress=self.update_progress_callback)

            if process_all:
                parent_dir = Path(data_dir).parent
                ndtiff_dirs = [
                    d for d in parent_dir.iterdir()
                    if d.is_dir() and (d / f"{d.name}_NDTiffStack.tif").exists()
                ]
                for nd_dir in ndtiff_dirs:
                    if nd_dir == Path(data_dir):
                        continue  # Skip the directory that has already been processed.
                    try:
                        self.update_progress_callback(file_label=nd_dir.name, label="Processing next...")
                        # Pass existing params so only file-specific fields are updated.
                        parser = NDTiffParser(nd_dir, self.params)
                        # TODO: Reuse WOTFs across files with matching image dimensions.
                        processor = QDPCProcessor(parser.get_dpc_data(), parser.get_dpc_params())
                        processor.process_and_save(output_path=save_dir,
                                                   update_progress=self.update_progress_callback)
                        self.update_progress_callback(label=f"Completed")
                    except Exception as exc:
                        self.update_progress_callback(label=f"Failed: {exc}")
                        raise

        except Exception as exc:
            self._end_progress_bar("Processing failed.")
            raise
        self._end_progress_bar("Processing complete!")


    def _on_process(self) -> None:
        p = self.params
        p.solver_type = self.solver_var.get()
        p.reg_method = self.method_var.get()
        p.wavelength = float(self.entries["wavelength"].get())
        p.na = float(self.entries["na"].get())
        p.na_in = float(self.entries["na_in"].get())
        p.magnification = float(self.entries["magnification"].get())
        p.camera_pixel_size = float(self.entries["camera_pixel_size"].get())
        p.dpc_rotations = [
            float(r.strip()) for r in self.entries["dpc_rotations"].get().split(",")
        ]
        if p.solver_type == "3D":
            p.z_step = float(self.entries["z_step"].get())
            p.ri_medium = float(self.entries["ri_medium"].get())

        p.regularisation_params[p.reg_method] = {
            key: float(self.entries[key].get())
            for key in p.regularisation_params[p.reg_method]
        }
        p.image_axes_slices = self._parse_axis_slices()
        p.bc_real = self.real_bc_combobox.get()
        p.bc_imag = self.imag_bc_combobox.get()
        p.use_gpu = self.use_gpu_var.get()

        threading.Thread(target=self.process).start()

    def _on_cancel(self) -> None:
        self.params = None
        self.root.quit()
        self.root.destroy()

    def show(self) -> QDPCProcessingParameters | None:
        """
        Display the GUI and block until the user closes it.
        Returns the user edited parameters, or None if the
        user cancelled.
        """
        self.root.mainloop()
        return self.params


def main() -> None:
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    gui = QDPCProcessorGUI()
    gui.show()


if __name__ == "__main__":
    main()