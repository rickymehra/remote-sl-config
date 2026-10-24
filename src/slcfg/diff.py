"""Byte-level diffs of SysEx dumps, in raw or alternate (7-bit-unpacked, nibblized) views."""

from __future__ import annotations

from dataclasses import dataclass

from .sysex import view


@dataclass(frozen=True)
class ByteDiff:
    offset: int
    a: int | None  # None when the byte only exists in the other file
    b: int | None


def diff_bytes(a: bytes, b: bytes) -> list[ByteDiff]:
    """Every offset where ``a`` and ``b`` differ, including length overhang."""
    out = [ByteDiff(i, x, y) for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y]
    longer, la = (a, True) if len(a) > len(b) else (b, False)
    for i in range(min(len(a), len(b)), len(longer)):
        out.append(ByteDiff(i, longer[i], None) if la else ByteDiff(i, None, longer[i]))
    return out


def diff_views(a: bytes, b: bytes, mode: str = "raw", skip: int = 0) -> list[ByteDiff]:
    """Diff after dropping ``skip`` leading bytes and transforming both inputs with ``mode``.

    Offsets in the result are relative to the transformed data (plus ``skip`` for raw view).
    """
    va, vb = view(a[skip:], mode), view(b[skip:], mode)
    diffs = diff_bytes(va, vb)
    if mode == "raw" and skip:
        diffs = [ByteDiff(d.offset + skip, d.a, d.b) for d in diffs]
    return diffs


def _fmt(v: int | None) -> str:
    if v is None:
        return "--  ---  -"
    ch = chr(v) if 32 <= v < 127 else "."
    return f"{v:02X}  {v:3d}  {ch}"


def format_diff(diffs: list[ByteDiff], *, record_base: int | None = None, stride: int = 0) -> str:
    """Render diffs as a table. With ``record_base``/``stride`` each offset also shows
    ``record#+field`` so single-control captures are easy to read."""
    lines = ["offset  hex   | a: hex dec chr | b: hex dec chr" + ("  | rec+fld" if stride else "")]
    for d in diffs:
        loc = ""
        if stride and record_base is not None and d.offset >= record_base:
            r, f = divmod(d.offset - record_base, stride)
            loc = f"  | r{r:02d}+{f:02d}"
        lines.append(f"{d.offset:6d}  {d.offset:04X}  | {_fmt(d.a)}     | {_fmt(d.b)}{loc}")
    lines.append(f"{len(diffs)} differing byte(s)")
    return "\n".join(lines)
