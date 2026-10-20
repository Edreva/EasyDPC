# =============================================================================
# qDPC Input Format Dispatch
#
# Copyright (C) 2026 Ewan Drever-Smith
# Free to use, redistribute and modify under GPLv3, see LICENSE.md for details.
# =============================================================================

"""
Opens the right parser for an input path and finds the sibling datasets to
include when batch processing. Both parsers expose the same interface:
get_dpc_params(), get_dpc_data(), update_dpc_params() and source_files.
"""


import re
from pathlib import Path

from .qdpc_processing_parameters import QDPCProcessingParameters
from .ome_tiff_parser import OMETiffParser, OME_SUFFIXES, TIFF_SUFFIXES


INPUT_FORMATS = ("NDTiff", "OME-TIFF")

# Output files written by QDPCProcessor, excluded from OME-TIFF batches.
_RESULT_PATTERN = re.compile(r"_[23]DqDPC(_\d+)?\.tiff?$", re.IGNORECASE)


def open_parser(
    path: Path | str,
    input_format: str,
    existing_params: QDPCProcessingParameters | None = None,
):
    """Return an NDTiffParser or OMETiffParser for *path*."""
    path = Path(path)
    if input_format == "NDTiff":
        if not path.is_dir():
            raise ValueError(
                "NDTiff input must be a directory. Switch the input format to "
                "OME-TIFF to open a single TIFF file."
            )
        # Imported lazily so OME-TIFF users do not need ndstorage installed.
        from .ndtiff_parser import NDTiffParser
        return NDTiffParser(path, existing_params)
    if input_format == "OME-TIFF":
        return OMETiffParser(path, existing_params)
    raise ValueError(f"Unknown input format '{input_format}'.")


def find_batch_inputs(path: Path | str, input_format: str) -> list[Path]:
    """
    Other datasets alongside *path* to process with the same parameters.
    NDTiff: sibling dataset directories in the parent directory.
    OME-TIFF: other .ome.tif(f) files in the same directory (or any .tif(f)
    if the selected file is not named .ome.tif), excluding qDPC outputs.
    """
    path = Path(path).resolve()
    if input_format == "NDTiff":
        candidates = [
            d for d in path.parent.iterdir()
            if d.is_dir() and (d / f"{d.name}_NDTiffStack.tif").exists()
        ]
    else:
        suffixes = OME_SUFFIXES if path.name.lower().endswith(OME_SUFFIXES) else TIFF_SUFFIXES
        candidates = [
            f for f in path.parent.iterdir()
            if f.is_file() and f.name.lower().endswith(suffixes)
            and not _RESULT_PATTERN.search(f.name)
        ]
    return sorted(c for c in candidates if c.resolve() != path)


def dataset_sources(parser) -> set[Path]:
    """All files/directories making up the dataset a parser has opened."""
    sources = getattr(parser, "source_files", None)
    if sources:
        return set(sources)
    return {Path(parser.get_dpc_params().input_file_path).resolve()}
