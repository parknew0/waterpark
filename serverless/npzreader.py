"""Read a .npz of plain integer arrays using only the standard library.

The handler looks up one cell per request. That needs an offset and a few
bytes, not an array library -- and numpy is the reason the deployment would
otherwise need a layer. AWS publishes its numpy-bearing layers up to Python
3.11, so a 3.12 function has to hunt for an ARN, pin a version, and re-pin it
whenever that version is retired. Dropping the dependency removes that whole
class of deployment problem: the function becomes stdlib-only.

.npz is a zip of .npy members, and .npy is a short ASCII header followed by
raw little-endian data, so both formats are readable with `zipfile` and
`struct`. Only the integer dtypes this project writes are supported; anything
else raises rather than silently misreading bytes.
"""

from __future__ import annotations

import ast
import struct
import zipfile
from pathlib import Path

NPY_MAGIC = b"\x93NUMPY"

# Only what build_serving_bundle.py emits. Values are (struct code, itemsize).
DTYPES = {
    "|u1": ("<B", 1),
    "<u1": ("<B", 1),
    "|i1": ("<b", 1),
    "<i2": ("<h", 2),
    "<u2": ("<H", 2),
    "<i4": ("<i", 4),
    "<u4": ("<I", 4),
}


class NpyError(RuntimeError):
    pass


class Array2D:
    """A read-only 2-D integer array backed by the raw .npy payload."""

    __slots__ = ("data", "rows", "cols", "code", "itemsize")

    def __init__(self, data: bytes, rows: int, cols: int, code: str, itemsize: int):
        self.data = data
        self.rows = rows
        self.cols = cols
        self.code = code
        self.itemsize = itemsize

    def at(self, row: int, col: int) -> int:
        """Value at (row, col). Raises IndexError outside the array."""
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            raise IndexError(f"({row}, {col}) outside {self.rows}x{self.cols}")
        offset = (row * self.cols + col) * self.itemsize
        return struct.unpack_from(self.code, self.data, offset)[0]


def _parse_npy(raw: bytes) -> Array2D:
    if not raw.startswith(NPY_MAGIC):
        raise NpyError("not a .npy payload")
    major = raw[6]
    if major == 1:
        header_len = struct.unpack_from("<H", raw, 8)[0]
        start = 10
    elif major == 2:
        header_len = struct.unpack_from("<I", raw, 8)[0]
        start = 12
    else:
        raise NpyError(f"unsupported .npy version {major}")

    header = raw[start : start + header_len].decode("latin1").strip()
    # The header is a Python dict literal, so literal_eval parses it without
    # executing anything.
    meta = ast.literal_eval(header)

    if meta.get("fortran_order"):
        raise NpyError("fortran-ordered arrays are not supported")
    shape = tuple(meta["shape"])
    if len(shape) != 2:
        raise NpyError(f"expected a 2-D array, got shape {shape}")
    descr = meta["descr"]
    if descr not in DTYPES:
        raise NpyError(f"unsupported dtype {descr!r}")

    code, itemsize = DTYPES[descr]
    data = raw[start + header_len :]
    expected = shape[0] * shape[1] * itemsize
    if len(data) < expected:
        raise NpyError(f"payload short: {len(data)} < {expected}")
    return Array2D(data, shape[0], shape[1], code, itemsize)


def load_npz(path: Path) -> dict[str, Array2D]:
    """Load every 2-D integer array in a .npz, keyed by member name."""
    arrays: dict[str, Array2D] = {}
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.endswith(".npy"):
                continue
            arrays[name[:-4]] = _parse_npy(archive.read(name))
    if not arrays:
        raise NpyError(f"no .npy members in {path}")
    return arrays
