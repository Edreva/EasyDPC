# =============================================================================
# Camera Information Manager
#
# Copyright (C) 2026 Ewan Drever-Smith
# Free to use, redistribute and modify under GPLv3, see LICENSE.md for details. 
# =============================================================================

"""
Camera information manager for handling camera pixel sizes and saving them for future use.
"""


import json
from pathlib import Path

from tkinter import simpledialog, messagebox


class CameraInfoManager:
    """Saves per-camera pixel sizes in a JSON file."""

    DEFAULT_JSON_PATH = Path(__file__).parent / "camera_pixel_sizes.json"

    def __init__(self, json_file: Path | None = None) -> None:
        self.json_file = json_file or self.DEFAULT_JSON_PATH
        self.camera_pixel_sizes: dict[str, float] = self._load()

    def _load(self) -> dict[str, float]:
        if self.json_file.exists():
            try:
                with open(self.json_file, "r") as f:
                    return json.load(f)
            except Exception as exc:
                print(f"Error loading camera pixel sizes: {exc}")
                return {}
        print("Camera pixel size JSON not found; starting with an empty dictionary.")
        return {}

    def _save(self) -> None:
        try:
            with open(self.json_file, "w") as f:
                json.dump(self.camera_pixel_sizes, f, indent=4)
        except Exception as exc:
            print(f"Error saving camera pixel sizes: {exc}")

    def get_camera_pixel_size(self, camera_name: str) -> float | None:
        if camera_name is None:
            print("Camera name is None; cannot retrieve pixel size.")
            return None
        if camera_name not in self.camera_pixel_sizes:
            pixel_size = self._prompt_for_pixel_size(camera_name)
            if pixel_size is not None:
                self.camera_pixel_sizes[camera_name] = pixel_size
                self._save()
        return self.camera_pixel_sizes.get(camera_name)

    def _prompt_for_pixel_size(self, camera_name: str) -> float | None:
        """Ask the user to enter the pixel size for an unknown camera."""
        while True:
            try:
                pixel_size = simpledialog.askfloat(
                    "Pixel Size Required",
                    f"Enter pixel size (µm) for camera '{camera_name}':",
                )
                if pixel_size is not None and pixel_size > 0:
                    return pixel_size
                messagebox.showerror(
                    "Invalid Input", "Please enter a positive number for pixel size."
                )
            except Exception as exc:
                messagebox.showerror("Error", f"An error occurred: {exc}")
                return None