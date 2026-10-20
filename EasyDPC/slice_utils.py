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


def parse_index_list(text: str, size: int) -> tuple[int, ...]:
    """
    Parse a comma separated list of indices and/or slices into explicit
    indices along an axis of length *size*. Order is preserved.
    i.e. '0,1,2,3' -> (0, 1, 2, 3), '0:4' -> (0, 1, 2, 3),
    '4:8, 0' -> (4, 5, 6, 7, 0), '-1' -> (size - 1,).
    Raises ValueError for empty input or out of range indices.
    """
    indices: list[int] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        if ":" in token:
            indices.extend(range(size)[str_to_slice(token)])
            continue
        index = int(token)
        if not -size <= index < size:
            raise ValueError(f"Index {index} is out of range for an axis of size {size}.")
        indices.append(index % size)
    if not indices:
        raise ValueError("No indices specified.")
    return tuple(indices)


def format_index_list(indices) -> str:
    """
    Inverse of parse_index_list for display. Contiguous ascending runs of
    three or more are collapsed to slice syntax, e.g. (0, 1, 2, 3) -> '0:4'.
    """
    indices = list(indices)
    parts: list[str] = []
    i = 0
    while i < len(indices):
        j = i
        while j + 1 < len(indices) and indices[j + 1] == indices[j] + 1:
            j += 1
        if j - i >= 2:
            parts.append(f"{indices[i]}:{indices[j] + 1}")
        else:
            parts.extend(str(v) for v in indices[i:j + 1])
        i = j + 1
    return ", ".join(parts)


def slice_to_str(s: slice) -> str:
    """Convert a slice object to a string representation."""
    start = "" if s.start is None else str(s.start)
    stop = "" if s.stop is None else str(s.stop)
    result = f"{start}:{stop}"
    if s.step is not None:
        result += f":{s.step}"
    return f"[{result}]"