"""Decode/encode ReMOTE SL (Mk1) template SysEx <-> :class:`slcfg.model.Template`.

Every field is described once in :data:`HEADER_FIELDS` / :data:`RECORD_FIELDS` (the
"offset table" from docs/FORMAT.md). Encoding starts from the original bytes (``_raw``) and
only rewrites a field whose decoded value changed, so ``encode(decode(x)) == x`` holds for
any input, including bytes we do not understand yet.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import model as m
from .sysex import EOX, SysexError, split_messages, split_u14_be, u14_be

# ---- message geometry (confirmed against 89 community dumps + 1 bulk dump) ------------------
MESSAGE_LEN = 4112
PREFIX = m.TEMPLATE_PREFIX  # F0 00 20 29 02 03
RECORD_BASE = m.HEADER_LEN
RECORD_LEN = m.RECORD_LEN
TRAILER_OFFSET = RECORD_BASE + m.NUM_RECORDS * RECORD_LEN  # 4109: "12 34 F7"
TEMPLATE_NAME_OFFSET = 13
SLOT_OFFSET = 12
BULK_FLAG_OFFSET = 7
GROUP_SIZE_OFFSET = 65
GROUP_POSITION_OFFSET = 66
SYSEX_LENGTH_OFFSET = 27

# Header of an empty user template (factory "User1" with name/slot cleared).
DEFAULT_HEADER = bytes.fromhex(
    "f000202902037f00002109000020202020202020202020202020202020202020202020202020202020202020"
    "2020202020202020202020202020202020000000000000005a29000000000000000000000000190001002100"
    "0900390011002900310105004400440000000400000000004700007f40000000000047000000400000000000"
    "470000004000000000004700000040"
) + bytes(272)
DEFAULT_RECORD = bytes.fromhex(
    "20" * 8 + "00 00 00 00 7f 00 51 00 00 00 47 40" + "00" * 7 + "01" + "00" * 13
)
DEFAULT_TRAILER = bytes([0x12, 0x34, EOX])
assert len(DEFAULT_HEADER) == RECORD_BASE and len(DEFAULT_RECORD) == RECORD_LEN


class CodecError(ValueError):
    pass


# ---- field codecs ---------------------------------------------------------------------------


def _ascii_get(b: bytes) -> str:
    return "".join(chr(c) if 0x20 <= c < 0x7F else "?" for c in b).rstrip(" ")


def _ascii_put(width: int) -> Callable[[Any], bytes]:
    def put(v: Any) -> bytes:
        return str(v).ljust(width)[:width].encode("ascii")

    return put


@dataclass(frozen=True)
class Field:
    """One entry of the offset table."""

    name: str  # attribute path on Control/Template ("sysex.length" for nested)
    offset: int
    size: int
    get: Callable[[bytes], Any]
    put: Callable[[Any], bytes]
    confidence: str  # confirmed | likely | guess
    note: str = ""


def _u7(name: str, off: int, conf: str, note: str = "") -> Field:
    return Field(name, off, 1, lambda b: b[0], lambda v: bytes([v & 0x7F]), conf, note)


def _u14(name: str, off: int, conf: str, note: str = "") -> Field:
    return Field(
        name, off, 2, lambda b: u14_be(b[0], b[1]), lambda v: bytes(split_u14_be(v)), conf, note
    )


RECORD_FIELDS: list[Field] = [
    Field("name", 0, 8, _ascii_get, _ascii_put(8), "confirmed", "8-char LCD label, space padded"),
    Field(
        "type",
        8,
        1,
        lambda b: m.type_name(b[0]),
        lambda v: bytes([m.type_code(v)]),
        "confirmed",
        "control type code (see CONTROL_TYPES)",
    ),
    _u14("low", 9, "likely", "LowVal; +9/+10 byte order is a guess (MSB first). MMC cmd, note no."),
    _u14("high", 11, "likely", "HighVal; same layout as low. MMC device id"),
    # +13 bits 2..4 = button mode; other bits stay in _raw
    Field(
        "button_mode",
        13,
        1,
        lambda b: m.BUTTON_MODES[b[0] & m.BUTTON_MODE_MASK],
        lambda v: bytes([m.BUTTON_MODE_CODES[v]]),
        "likely",
        "bits 2..4 of +13; other bits preserved",
    ),
    _u7("display", 15, "likely", "DispType: 0=0-127, 1=-64/+63, others unconfirmed"),
    _u7("number_msb", 16, "likely", "NRPN/RPN MSB"),
    _u7("number", 17, "confirmed", "CC number / NRPN LSB / RPN LSB"),
    _u7("port", 18, "guess", "port routing code"),
    _u7("channel", 19, "guess", "MIDI channel code"),
    _u14("value", 20, "likely", "stored control value"),
    _u7("step", 22, "likely", "StepVal for STEP buttons"),
    _u7("sysex.data_type", 26, "likely", "0=NONE 1=SINGLE"),
    _u7("sysex.length", 27, "likely", "sysex length, 0..12"),
    _u7("sysex.data_position", 28, "likely", "1-based position of the variable byte"),
    Field(
        "sysex.data",
        29,
        12,
        lambda b: list(b),
        lambda v: bytes([*v, *([0] * (12 - len(v)))]),
        "likely",
        "sysex body without F0/F7",
    ),
]

HEADER_FIELDS: list[Field] = [
    Field(
        "slot",
        SLOT_OFFSET,
        1,
        lambda b: b[0] + 1,
        lambda v: bytes([v - 1]),
        "confirmed",
        "0-based memory location",
    ),
    Field(
        "name",
        TEMPLATE_NAME_OFFSET,
        m.TEMPLATE_NAME_LEN,
        _ascii_get,
        _ascii_put(m.TEMPLATE_NAME_LEN),
        "confirmed",
        "48-char template name",
    ),
    _u7("group_size", GROUP_SIZE_OFFSET, "likely", "template group size"),
    _u7("group_position", GROUP_POSITION_OFFSET, "likely", "position within group"),
]


def _getattr_path(obj: Any, path: str) -> Any:
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def _setattr_path(obj: Any, path: str, value: Any) -> None:
    *head, last = path.split(".")
    for part in head:
        obj = getattr(obj, part)
    setattr(obj, last, value)


def _decode_fields(obj: Any, fields: list[Field], buf: bytes) -> None:
    for f in fields:
        _setattr_path(obj, f.name, f.get(buf[f.offset : f.offset + f.size]))


def _encode_fields(obj: Any, fields: list[Field], buf: bytearray) -> None:
    orig = bytes(buf)
    for f in fields:
        value = _getattr_path(obj, f.name)
        current = f.get(orig[f.offset : f.offset + f.size])
        if f.name == "sysex.data":
            # decode shows only the first `length` bytes; compare like with like
            current = current[: min(orig[SYSEX_LENGTH_OFFSET], m.SYSEX_MAX)]
        if value == current:
            continue  # untouched: keep the original bytes exactly
        if f.name == "button_mode":
            # only bits 2..4 belong to the button mode
            keep = orig[f.offset] & ~m.BUTTON_MODE_MASK & 0x7F
            buf[f.offset] = keep | m.BUTTON_MODE_CODES[value]
            continue
        buf[f.offset : f.offset + f.size] = f.put(value)


# ---- public API -----------------------------------------------------------------------------


def decode_control(slot: m.Slot, rec: bytes) -> m.Control:
    if len(rec) != RECORD_LEN:
        raise CodecError(f"record must be {RECORD_LEN} bytes")
    c = m.Control(slot=slot.key, raw=bytes(rec))
    _decode_fields(c, RECORD_FIELDS, rec)
    # Show only the used part of the sysex buffer.
    if c.sysex.length <= m.SYSEX_MAX:
        c.sysex.data = c.sysex.data[: c.sysex.length]
    return c


def encode_control(c: m.Control) -> bytes:
    c.validate()
    buf = bytearray(c.raw if c.raw is not None else DEFAULT_RECORD)
    _encode_fields(c, RECORD_FIELDS, buf)
    return bytes(buf)


def decode(msg: bytes) -> m.Template:
    """Decode one 4112-byte template message."""
    if len(msg) != MESSAGE_LEN:
        raise CodecError(f"expected {MESSAGE_LEN}-byte template message, got {len(msg)}")
    if not msg.startswith(PREFIX) or msg[-1] != EOX:
        raise CodecError("not a ReMOTE SL template (header F0 00 20 29 02 03 ... F7 expected)")
    t = m.Template(header_raw=bytes(msg[:RECORD_BASE]), trailer_raw=bytes(msg[TRAILER_OFFSET:]))
    _decode_fields(t, HEADER_FIELDS, msg)
    for s in m.SLOTS:
        off = RECORD_BASE + s.index * RECORD_LEN
        t.controls[s.key] = decode_control(s, msg[off : off + RECORD_LEN])
    return t


def encode(t: m.Template) -> bytes:
    t.validate()
    head = bytearray(t.header_raw if t.header_raw is not None else DEFAULT_HEADER)
    _encode_fields(t, HEADER_FIELDS, head)
    body = bytearray()
    for s in m.SLOTS:
        c = t.controls.get(s.key)
        body += encode_control(c) if c is not None else DEFAULT_RECORD
    out = (
        bytes(head)
        + bytes(body)
        + (t.trailer_raw if t.trailer_raw is not None else DEFAULT_TRAILER)
    )
    if len(out) != MESSAGE_LEN:
        raise CodecError(f"encoded length {len(out)} != {MESSAGE_LEN}")
    return out


def decode_file(data: bytes) -> list[m.Template]:
    """Decode a .syx file holding one template or a bulk dump of several."""
    try:
        msgs = split_messages(data)
    except SysexError as e:
        raise CodecError(str(e)) from e
    if not msgs:
        raise CodecError("no SysEx messages found")
    return [decode(msg.data) for msg in msgs]


def encode_file(templates: list[m.Template]) -> bytes:
    return b"".join(encode(t) for t in templates)


def is_bulk(t: m.Template) -> bool:
    """Bulk-dump members carry 01 at header byte 7 (single-template files carry 00)."""
    return bool(t.header_raw and t.header_raw[BULK_FLAG_OFFSET] == 1)
