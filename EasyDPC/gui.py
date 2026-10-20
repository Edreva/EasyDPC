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
import copy
import threading

import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk

from .docs import DOCS
from .slice_utils import str_to_slice, parse_index_list, format_index_list
from .qdpc_processing_parameters import QDPCProcessingParameters
from .qdpc_processor import QDPCProcessor
from .dataset_io import INPUT_FORMATS, open_parser, find_batch_inputs, dataset_sources


class QDPCProcessorGUI:
    """GUI for selecting an NDTiff directory or OME-TIFF file and adjusting
    DPC processing parameters before the solver is invoked.

    The format selector and input picker row are shown immediately on open.
    The rest of the form is revealed only after a valid input has been
    selected and its metadata successfully parsed. For OME-TIFF input an
    extra Axis Assignment section lets the user say which axis holds the
    DPC images, which indices along it to use, and which axis is z.
    TODO: Allow for pixel binning in addition to current X/Y subsampling via slice entries
    """

    INITIAL_SIZE = (500, 200)
    EXPANDED_HEIGHT = 900
    DOCS_WIDTH = 280
    MAIN_FRAME_PADX = 10
    DOC_HIGHLIGHT_COLOR = ("gray75", "gray30")
    NOTE_COLOR = ("#8a5300", "#f0b45a")
    UNSET_CHANNEL_AXIS = "Select axis…"
    UNSET_Z_AXIS = "None"

    # Labels that change with the selected input format.
    FORMAT_LABELS = {
        "NDTiff": {
            "open_dir": "Input (NDTiff) Directory",
            "process_all": "Process all NDTiff in parent directory?",
        },
        "OME-TIFF": {
            "open_dir": "Input (OME-TIFF) File",
            "process_all": "Process all OME-TIFF files in the same directory?",
        },
    }

    def __init__(self) -> None:
        self.params: QDPCProcessingParameters | None = None
        self._parser = None

        self.root = ctk.CTk()
        self.root.title("EasyDPC - qDPC Processor")
        self.input_format_var = tk.StringVar(value=INPUT_FORMATS[0])

        self.arrayfire_installed = True
        try:
            import arrayfire
        except ImportError:
            self.arrayfire_installed = False

        self.labels = {
            "input_format":         "Input Format",
            "open_dir":             "Input (NDTiff) Directory / (OME-TIFF) File",
            "save_dir":             "Output Directory",
            "process_all":          "Process all datasets alongside the input?",
            "metadata":             "Detected Metadata",
            "axis_roles":           "Axis Assignment",
            "stack_shape":          "Stack shape",
            "channel_axis":         "DPC channel axis",
            "dpc_indices":          "DPC indices",
            "z_axis":               "Z axis [3D only]",
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

        self._build_format_selector(self._main, row=1)
        self._build_directory_row(self._main, row=2, key="open_dir")
        # Remaining sections are built and revealed in _on_input_selected().
        self.root.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _build_format_selector(self, parent: ctk.CTkFrame, row: int) -> int:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E))
        ctk.CTkLabel(
            frame, text=self.labels["input_format"], font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        ctk.CTkSegmentedButton(
            frame, values=list(INPUT_FORMATS), variable=self.input_format_var,
            command=self._on_format_changed,
        ).grid(row=0, column=1, sticky=tk.W)
        self._bind_hover(frame, "input_format")
        return row + 1

    def _on_format_changed(self, input_format: str) -> None:
        """Reset the input row and hide any form built for the other format."""
        self._row_labels["open_dir"].configure(text=self.FORMAT_LABELS[input_format]["open_dir"])
        self.entries["open_dir"].delete(0, tk.END)
        self._status_label.configure(text="")
        if hasattr(self, "_form_frame"):
            self._form_frame.destroy()
            del self._form_frame
            self._clear_form_entries()
        self.params = None
        self._parser = None
        self.root.geometry(f"{self.INITIAL_SIZE[0]}x{self.INITIAL_SIZE[1]}")

    def _clear_form_entries(self) -> None:
        """Forget entries belonging to the form, keeping the input path row."""
        for key in [k for k in self.entries if k != "open_dir"]:
            del self.entries[key]

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

        try:
            widget.bind("<Enter>", lambda _e, k=doc_key: self._hover_doc(k), add="+")
            widget.bind("<Leave>", lambda _e: self._clear_doc(), add="+")
        except NotImplementedError:
            # Some composite CTk widgets (e.g. CTkSegmentedButton) refuse
            # bind(); their child widgets are still bound below.
            pass
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
        label_text = self.FORMAT_LABELS[self.input_format_var.get()].get(key, self.labels[key])
        row_label = ctk.CTkLabel(
            dir_frame, text=label_text, font=ctk.CTkFont(size=13, weight="bold")
        )
        row_label.grid(row=0, column=0, sticky=tk.W, pady=(10, 5))
        if not hasattr(self, "_row_labels"):
            self._row_labels: dict[str, ctk.CTkLabel] = {}
        self._row_labels[key] = row_label

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
            self._status_label = ctk.CTkLabel(parent, text="", wraplength=self.INITIAL_SIZE[0] - 40,
                                              justify=tk.LEFT)
            self._status_label.grid(row=row + 1, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))
            # Typing / pasting a path and pressing Enter also loads it.
            path_entry.bind("<Return>", lambda _e: self._on_input_selected(path_entry.get().strip()))
            self._form_start_row = row + 2

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
        if entry_key != "open_dir":
            path = filedialog.askdirectory(title="Select Output Directory")
        elif self.input_format_var.get() == "OME-TIFF":
            path = filedialog.askopenfilename(
                title="Select OME-TIFF File",
                filetypes=[("OME-TIFF", "*.ome.tif *.ome.tiff"),
                           ("TIFF", "*.tif *.tiff"), ("All files", "*")],
            )
        else:
            path = filedialog.askdirectory(title="Select NDTiff Directory")
        if path:
            self.entries[entry_key].delete(0, tk.END)
            self.entries[entry_key].insert(0, path)
            # Only the input row triggers metadata parsing.
            if entry_key == "open_dir":
                self._on_input_selected(path)

    def _on_input_selected(self, path: str) -> None:
        """Parse metadata from *path* and reveal the parameter form."""
        if not path:
            return
        self._status_label.configure(text="Parsing metadata...")
        self.root.update_idletasks()
        try:
            parser = open_parser(path, self.input_format_var.get())
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
            self._clear_form_entries()

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
        row = self._build_axes_section(self._form_frame, row)
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

        if self.params.input_format == "OME-TIFF":
            # Axes as reported by the file; roles are assigned further down.
            shape_rows = self._parser.metadata_summary()
        else:
            shape_rows = [
                ("Image size", " x ".join(str(s) for s in self.params.image_shape)),
                ("Axis order", ", ".join(str(a) for a in self.params.image_axis_order)),
            ]
        labels = [
            ("Input file", Path(self.params.input_file_path).name),
            *shape_rows,
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

        notes = getattr(self._parser, "notes", [])
        if notes:
            notes_label = ctk.CTkLabel(
                parent, text="\n".join(f"• {n}" for n in notes), justify=tk.LEFT,
                text_color=self.NOTE_COLOR, wraplength=self.INITIAL_SIZE[0] - 60, anchor="w",
            )
            notes_label.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))
            self._bind_hover(notes_label, doc_key="metadata")
            row += 1

        return row + 1

    def _build_process_all_section(self, parent: ctk.CTkFrame, row: int) -> int:
        self.process_all_var = tk.BooleanVar(value=False)
        process_all_cb = ctk.CTkCheckBox(
            parent,
            text=self.FORMAT_LABELS[self.params.input_format]["process_all"],
            variable=self.process_all_var,
        )
        process_all_cb.grid(row=row, columnspan=2, column=0, sticky=tk.W)
        self._bind_hover(process_all_cb, "process_all")
        return row + 1

    def _build_axes_section(self, parent: ctk.CTkFrame, row: int) -> int:
        """
        Container for the axis assignment (OME-TIFF only) and axis slice
        sections, which are rebuilt whenever axis roles or shape change.
        """
        self._axes_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._axes_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E))
        self._axes_frame.grid_columnconfigure(0, weight=1)
        self._axes_frame.grid_columnconfigure(1, weight=2)
        self._populate_axes_frame()
        return row + 1

    def _populate_axes_frame(self) -> None:
        # Keep slice text the user typed for axes that still exist after a rebuild.
        previous = {k: e.get() for k, e in self.entries.items() if k.endswith("_slice")}
        for key in [k for k in self.entries
                    if k.endswith("_slice") or k in ("dpc_indices", "stack_shape")]:
            del self.entries[key]
        for child in self._axes_frame.winfo_children():
            child.destroy()

        row = 0
        if self.params.input_format == "OME-TIFF":
            row = self._build_axis_assignment_section(self._axes_frame, row)
        self._build_slice_section(self._axes_frame, row, previous)

    def _axis_label(self, axis: int | None, unset: str) -> str:
        return unset if axis is None else self._parser.describe_axis(axis)

    def _build_axis_assignment_section(self, parent: ctk.CTkFrame, row: int) -> int:
        """Controls for the user to say how the OME-TIFF axes map onto DPC."""
        row = self._separator(parent, row)
        row = self._section_label(parent, row, self.labels["axis_roles"])
        parser = self._parser
        p = self.params

        if p.channel_axis is None:
            hint = ctk.CTkLabel(parent, text="Select the axis that holds the DPC images.",
                                text_color=self.NOTE_COLOR)
            hint.grid(row=row, column=0, columnspan=2, sticky=tk.W)
            self._bind_hover(hint, "channel_axis")
            row += 1

        # Stack shape: lets a flattened page sequence be split into axes.
        if parser.planes_per_series > 1:
            ctk.CTkLabel(
                parent, text=f"{self.labels['stack_shape']} ({parser.planes_per_series} planes):"
            ).grid(row=row, column=0, sticky=tk.W, pady=2)
            shape_frame = ctk.CTkFrame(parent, fg_color="transparent")
            shape_frame.grid(row=row, column=1, sticky=tk.EW, pady=2)
            shape_frame.grid_columnconfigure(0, weight=1)
            shape_entry = ctk.CTkEntry(shape_frame)
            shape_entry.insert(0, ", ".join(str(n) for n in parser.stack_shape))
            shape_entry.grid(row=0, column=0, sticky=tk.EW, padx=(0, 6))
            shape_entry.bind("<Return>", lambda _e: self._on_stack_shape_apply())
            ctk.CTkButton(shape_frame, text="Apply", width=60,
                          command=self._on_stack_shape_apply).grid(row=0, column=1)
            self.entries["stack_shape"] = shape_entry
            self._bind_hover(shape_frame, "stack_shape")
            row += 1

        self._axis_choices = {parser.describe_axis(a): a for a in parser.selectable_axes()}

        ctk.CTkLabel(parent, text=f"{self.labels['channel_axis']}:").grid(
            row=row, column=0, sticky=tk.W, pady=2)
        self._channel_axis_combo = ctk.CTkComboBox(
            parent, values=[self.UNSET_CHANNEL_AXIS, *self._axis_choices], state="readonly",
            command=lambda _v: self._on_axis_roles_changed(changed="channel"),
        )
        self._channel_axis_combo.set(self._axis_label(p.channel_axis, self.UNSET_CHANNEL_AXIS))
        self._channel_axis_combo.grid(row=row, column=1, sticky=tk.EW, pady=2)
        self._bind_hover(self._channel_axis_combo, "channel_axis")
        row += 1

        row = self._build_labelled_entry(
            parent, row, f"{self.labels['dpc_indices']}:", "dpc_indices",
            format_index_list(p.dpc_channel_idxs),
        )
        dpc_entry = self.entries["dpc_indices"]
        dpc_entry.bind("<Return>", lambda _e: self._apply_dpc_indices(sync_rotations=True))
        dpc_entry.bind("<FocusOut>", lambda _e: self._apply_dpc_indices(
            sync_rotations=True, show_errors=False))
        if p.channel_axis is None:
            dpc_entry.configure(state="disabled")

        names = parser.channel_names_for_axis(p.channel_axis)
        if names:
            names_label = ctk.CTkLabel(
                parent, text="  ".join(f"{i}: {n}" for i, n in enumerate(names)),
                font=ctk.CTkFont(size=11), wraplength=self.INITIAL_SIZE[0] - 60, justify=tk.LEFT,
            )
            names_label.grid(row=row, column=1, sticky=tk.W)
            self._bind_hover(names_label, "dpc_indices")
            row += 1

        ctk.CTkLabel(parent, text=f"{self.labels['z_axis']}:").grid(
            row=row, column=0, sticky=tk.W, pady=2)
        self._z_axis_combo = ctk.CTkComboBox(
            parent, values=[self.UNSET_Z_AXIS, *self._axis_choices], state="readonly",
            command=lambda _v: self._on_axis_roles_changed(changed="z"),
        )
        self._z_axis_combo.set(self._axis_label(p.z_axis, self.UNSET_Z_AXIS))
        self._z_axis_combo.grid(row=row, column=1, sticky=tk.EW, pady=2)
        self._bind_hover(self._z_axis_combo, "z_axis")
        return row + 1

    def _set_entry(self, key: str, text: str) -> None:
        entry = self.entries.get(key)
        if entry is not None:
            entry.delete(0, tk.END)
            entry.insert(0, text)

    def _set_rotations(self, rotations) -> None:
        self.params.dpc_rotations = tuple(rotations)
        self._set_entry("dpc_rotations", ", ".join(str(r) for r in rotations))

    def _read_rotations(self) -> list[float]:
        """Parse the rotations entry. Raises ValueError on invalid input."""
        text = self.entries["dpc_rotations"].get()
        return [float(r) for r in text.split(",") if r.strip()]

    def _on_axis_roles_changed(self, changed: str) -> None:
        channel = self._axis_choices.get(self._channel_axis_combo.get())
        z = self._axis_choices.get(self._z_axis_combo.get())
        if channel is not None and channel == z:
            # The same axis cannot be both: the newly chosen role wins.
            if changed == "channel":
                z = None
            else:
                channel = None
        channel_changed = channel != self.params.channel_axis
        try:
            self._parser.set_axis_roles(channel, z)
        except ValueError as exc:
            messagebox.showerror("Invalid axis assignment", str(exc))
            return
        if channel_changed:
            # Suggest DPC indices for the new channel axis.
            idxs, rotations = self._parser.default_dpc_selection(channel)
            self.params.dpc_channel_idxs = idxs
            self._set_rotations(rotations)
        self._set_3d_default()
        # Rebuild after the combobox callback has returned.
        self.root.after_idle(self._populate_axes_frame)

    def _apply_dpc_indices(self, sync_rotations: bool = False, show_errors: bool = True) -> bool:
        """
        Validate the DPC indices entry and store it in the parameters.
        If *sync_rotations*, regenerate the rotations when their count no
        longer matches the number of DPC images.
        """
        entry = self.entries.get("dpc_indices")
        p = self.params
        if entry is None or p.channel_axis is None:
            if show_errors:
                messagebox.showerror("No channel axis",
                                     "Select the DPC channel axis under Axis Assignment.")
            return False
        try:
            idxs = parse_index_list(entry.get(), p.image_shape[p.channel_axis])
            self._parser.set_dpc_indices(idxs)
        except ValueError as exc:
            if show_errors:
                messagebox.showerror("Invalid DPC indices", str(exc))
            return False
        if sync_rotations:
            try:
                count_matches = len(self._read_rotations()) == len(idxs)
            except ValueError:
                count_matches = False
            if not count_matches:
                self._set_rotations(self._parser.rotations_for(idxs, p.channel_axis))
        return True

    def _on_stack_shape_apply(self) -> None:
        text = self.entries["stack_shape"].get()
        try:
            shape = [int(v) for v in text.replace("x", ",").replace("×", ",").split(",") if v.strip()]
            self._parser.set_stack_shape(shape or None)
        except ValueError as exc:
            messagebox.showerror("Invalid stack shape", str(exc))
            return
        self._set_rotations(())
        self._set_3d_default()
        self.root.after_idle(self._populate_axes_frame)

    def _default_solver(self) -> str:
        p = self.params
        has_z = p.z_axis is not None and p.image_shape[p.z_axis] > 1
        return "3D" if p.z_step and has_z else "2D"

    def _set_3d_default(self) -> None:
        """Fall back to the 2D solver if the z axis has been unassigned."""
        if hasattr(self, "solver_var") and self.solver_var.get() == "3D" and self.params.z_axis is None:
            self.solver_var.set("2D")
            self._set_3d_params_enabled(False)

    def _build_slice_section(self, parent: ctk.CTkFrame, row: int,
                             previous: dict[str, str] | None = None) -> int:
        row = self._separator(parent, row)
        row = self._section_label(parent, row, self.labels["slices"])
        previous = previous or {}

        for i, axis in enumerate(self.params.image_axis_order):
            if axis == "channel" or self.params.image_shape[i] <= 1:
                # DPC channels identified elsewhere.
                continue
            label = f"{axis} (size {self.params.image_shape[i]}):"
            entry_key = f"{axis}_slice"
            default = previous.get(entry_key, ":")
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
        self.solver_var = tk.StringVar(value=self._default_solver())
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

    def _parse_axis_slices(self) -> list[slice] | None:
        """
        Read axis slice strings from the GUI entries and return
        a list of slice objects in axis order.

        Shows an error and returns None on parse failure.
        """
        slices: list[slice] = []
        for axis in self.params.image_axis_order:
            if axis == "channel":
                if self.params.input_format == "OME-TIFF":
                    # OME-TIFF reads dpc_channel_idxs directly (any order).
                    slices.append(slice(None))
                    continue
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
                return None
        return slices

    def process(self) -> None:
        data_path = Path(self.params.input_file_path)
        input_format = self.params.input_format
        save_dir = str(self.entries['save_dir'].get())
        failures: list[str] = []

        try:
            process_all = self.process_all_var.get() if hasattr(self, 'process_all_var') else False
            batch = find_batch_inputs(data_path, input_format) if process_all else []

            self._start_progress_bar(file_label=data_path.name, progress_label="Starting Processing...")
            processor = QDPCProcessor(self._parser.get_dpc_data(), self.params)
            processor.process_and_save(output_path=save_dir,
                                       update_progress=self.update_progress_callback)

            # Multi-file OME-TIFF datasets are opened via any one of their
            # files, so skip files belonging to a dataset already processed.
            processed = dataset_sources(self._parser)
            # Batch files update a copy, so the form's parameters (and the
            # dataset they describe) are unchanged if Process is run again.
            batch_params = copy.deepcopy(self.params)
            for path in batch:
                if path.resolve() in processed:
                    continue
                try:
                    self.update_progress_callback(file_label=path.name, label="Processing next...")
                    # Pass existing params so only file-specific fields are updated.
                    parser = open_parser(path, input_format, batch_params)
                    processed |= dataset_sources(parser)
                    # TODO: Reuse WOTFs across files with matching image dimensions.
                    processor = QDPCProcessor(parser.get_dpc_data(), parser.get_dpc_params())
                    processor.process_and_save(output_path=save_dir,
                                               update_progress=self.update_progress_callback)
                    self.update_progress_callback(label=f"Completed")
                except Exception as exc:
                    # Skip incompatible / failed datasets and carry on with the rest.
                    print(f"Failed to process {path}: {exc}")
                    self.update_progress_callback(label=f"Failed: {exc}")
                    failures.append(path.name)

        except Exception as exc:
            self._end_progress_bar(f"Processing failed: {exc}")
            raise
        if failures:
            self._end_progress_bar(f"Processing complete, {len(failures)} failed: {', '.join(failures)}")
        else:
            self._end_progress_bar("Processing complete!")

    def _validate_dpc_selection(self) -> bool:
        """Check the DPC images and rotations are consistent before solving."""
        p = self.params
        if p.input_format == "OME-TIFF" and not self._apply_dpc_indices():
            return False
        if not p.dpc_channel_idxs:
            messagebox.showerror("No DPC images", "No DPC images have been selected.")
            return False
        if len(p.dpc_rotations) != len(p.dpc_channel_idxs):
            messagebox.showerror(
                "Rotation count mismatch",
                f"{len(p.dpc_rotations)} source rotation(s) given for "
                f"{len(p.dpc_channel_idxs)} DPC image(s); enter one rotation per DPC image.",
            )
            return False
        if p.solver_type == "3D" and (p.z_axis is None or p.image_shape[p.z_axis] < 2):
            messagebox.showerror(
                "No z axis",
                "The 3D solver needs a z axis with more than one plane"
                + (": assign one under Axis Assignment." if p.input_format == "OME-TIFF" else "."),
            )
            return False
        return True

    def _on_process(self) -> None:
        p = self.params
        p.solver_type = self.solver_var.get()
        p.reg_method = self.method_var.get()
        try:
            p.wavelength = float(self.entries["wavelength"].get())
            p.na = float(self.entries["na"].get())
            p.na_in = float(self.entries["na_in"].get())
            p.magnification = float(self.entries["magnification"].get())
            p.camera_pixel_size = float(self.entries["camera_pixel_size"].get())
            p.dpc_rotations = self._read_rotations()
            if p.solver_type == "3D":
                p.z_step = float(self.entries["z_step"].get())
                p.ri_medium = float(self.entries["ri_medium"].get())

            p.regularisation_params[p.reg_method] = {
                key: float(self.entries[key].get())
                for key in p.regularisation_params[p.reg_method]
            }
        except ValueError as exc:
            messagebox.showerror("Invalid parameter", f"Could not read a numeric parameter: {exc}")
            return
        if not self._validate_dpc_selection():
            return
        slices = self._parse_axis_slices()
        if slices is None:
            return
        p.image_axes_slices = slices
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