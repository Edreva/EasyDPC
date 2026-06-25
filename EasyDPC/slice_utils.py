# =============================================================================
# Slice utilities
#
# Copyright (C) 2026 Ewan Drever-Smith
# Free to use, redistribute and modify under GPLv3, see LICENSE.md for details. 
# =============================================================================

"""
Slice utilities for handling slice objects and their string representations.
"""


def str_to_slice(slice_str: str) -> slice:
    """
    Convert a string representation of a slice to a slice object.
    i.e. '0:10' -> slice(0, 10), '5' -> slice(5, 6), 
    ':' -> slice(None, None), '0:20:2' -> slice(0, 20, 2).
    """
    parse_int = lambda v: int(v.strip()) if v.strip() else None
    if ":" in slice_str:
        return slice(*map(parse_int, slice_str.split(":")))
    index = int(slice_str.strip())
    return slice(index, index + 1)


def slice_to_str(s: slice) -> str:
    """Convert a slice object to a string representation."""
    start = "" if s.start is None else str(s.start)
    stop = "" if s.stop is None else str(s.stop)
    result = f"{start}:{stop}"
    if s.step is not None:
        result += f":{s.step}"
    return f"[{result}]"