"""Data model for a ReMOTE SL (Mk1) template.

The physical layout and record order come from docs/FORMAT.md. Field values that are not
yet understood are kept as raw 7-bit codes, never guessed into a friendlier shape, so an
edit in the TUI or JSON always maps to exactly one byte change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

NAME_LEN = 8
TEMPLATE_NAME_LEN = 48
NUM_RECORDS = 90
NUM_SLOTS = 40
SYSEX_MAX = 12
RECORD_LEN = 41
HEADER_LEN = 419  # bytes before the first control record
TRAILER_LEN = 3  # "12 34 F7"
TEMPLATE_PREFIX = bytes([0xF0, 0x00, 0x20, 0x29, 0x02, 0x03])  # SysEx start, Novation, SL


@dataclass(frozen=True)
class Slot:
    index: int  # record number inside the template (0..89)
    key: str  # stable JSON key, e.g. "encoder_1"
    group: str  # control family
    label: str  # human label for the TUI


def _row(group: str, base: int, label: str) -> list[Slot]:
    return [Slot(base + i, f"{group}_{i + 1}", group, f"{label} {i + 1}") for i in range(8)]


# Record order (FORMAT.md "Control records"). Button rows: on the left half the two rows sit
# behind (row 1) and in front of (row 2) the encoders; on the right half they sit in front
# of the sliders, row 3 nearer the sliders, row 4 nearest the keys.
SLOTS: list[Slot] = [
    *_row("encoder", 0, "Encoder"),
    *_row("pot", 8, "Pot"),
    *_row("slider", 16, "Slider"),
    *_row("button_row1", 24, "Btn R1"),
    *_row("button_row2", 32, "Btn R2"),
    *_row("button_row3", 40, "Btn R3"),
    *_row("button_row4", 48, "Btn R4"),
    *_row("drum_pad", 56, "Pad"),
    Slot(64, "expression", "pedal", "Expression"),
    Slot(65, "sustain", "pedal", "Sustain"),
    Slot(66, "mod", "joystick", "Joy Y"),
    Slot(67, "pitch", "joystick", "Joy X"),
    Slot(68, "touchpad_x1", "touchpad", "Touch X1"),
    Slot(69, "touchpad_y1", "touchpad", "Touch Y1"),
    Slot(70, "touchpad_x2", "touchpad", "Touch X2"),
    Slot(71, "touchpad_y2", "touchpad", "Touch Y2"),
    Slot(72, "rewind", "transport", "Rewind"),
    Slot(73, "forward", "transport", "Forward"),
    Slot(74, "stop", "transport", "Stop"),
    Slot(75, "play", "transport", "Play"),
    Slot(76, "record", "transport", "Record"),
    Slot(77, "loop", "transport", "Loop"),
    *[Slot(78 + i, f"extra_{i + 1}", "extra", f"Extra {i + 1}") for i in range(12)],
]
SLOT_BY_KEY = {s.key: s for s in SLOTS}
SLOT_BY_INDEX = {s.index: s for s in SLOTS}
assert len(SLOTS) == NUM_RECORDS

# Control type byte (record offset 8). Values marked (guess) never appear in community dumps.
CONTROL_TYPES: dict[int, str] = {
    0: "none",
    1: "cc",
    2: "nrpn",
    3: "rpn",
    4: "sysex",
    5: "mmc",
    6: "note",
    7: "program_change",  # guess
    8: "bank_change",  # guess
    9: "realtime",  # guess
    10: "pitch_bend",
    11: "drum_note",
    12: "template",
}
CONTROL_TYPE_CODES = {v: k for k, v in CONTROL_TYPES.items()}


def type_name(code: int) -> str:
    return CONTROL_TYPES.get(code, f"type_{code}")


def type_code(name: str) -> int:
    if name in CONTROL_TYPE_CODES:
        return CONTROL_TYPE_CODES[name]
    m = re.fullmatch(r"type_(\d+)", name)
    if m and int(m.group(1)) < 128:
        return int(m.group(1))
    raise ValidationError(f"unknown control type {name!r}")


# Button mode lives in bits 2..4 of record offset 13. Drum pads report "momentary" for what
# the manual calls VELOCITY (pads cannot detect release).
BUTTON_MODES: dict[int, str] = {0: "normal", 4: "momentary", 8: "toggle", 16: "step"}
BUTTON_MODE_MASK = 0x1C
# Name every 3-bit combination so decode is always invertible.
for _code in range(0, BUTTON_MODE_MASK + 1, 4):
    BUTTON_MODES.setdefault(_code, f"bits_{_code}")
BUTTON_MODE_CODES = {v: k for k, v in BUTTON_MODES.items()}

# Display type (record offset 15). Only 0 and 1 are well supported by evidence.
DISPLAY_TYPES: dict[int, str] = {0: "0-127", 1: "-64/+63"}

# Channel and port routing codes, confirmed on hardware (FORMAT.md R18/R19, header 99-102).
# Record +19 channel: bit 6 set = explicit, low nibble = channel - 1; clear = follow the
# template's keyboard (bit 5) or common channel. Record +18 port: bit 6 set = explicit mask
# (U1/U2/U3 = bits 2/3/4, M1/M2 = bits 0/1, order untested); clear = follow keyboard (bit 5)
# or common port. The template header holds a plain 0-based channel and an explicit port mask.
ROUTE_EXPLICIT = 0x40
ROUTE_KEYBOARD = 0x20
PORT_BITS: list[tuple[int, str]] = [
    (0x04, "U1"),
    (0x08, "U2"),
    (0x10, "U3"),
    (0x01, "M1"),
    (0x02, "M2"),
]
PORT_MASK = 0x1F
KEYBOARD_CHANNEL_OFFSET = 99
KEYBOARD_PORT_OFFSET = 100
COMMON_CHANNEL_OFFSET = 101
COMMON_PORT_OFFSET = 102
# Values in an empty template (codec.DEFAULT_HEADER): channel 1, port U1
DEFAULT_TEMPLATE_CHANNEL = 0
DEFAULT_TEMPLATE_PORT = 0x44


def port_mask_name(code: int) -> str:
    names = [n for bit, n in PORT_BITS if code & bit]
    return "+".join(names) if names else "none"


def describe_channel(code: int) -> str:
    """Meaning of a control's channel code (record +19)."""
    if code & ROUTE_EXPLICIT:
        return f"ch {(code & 0x0F) + 1}"
    return "KeybCHAN" if code & ROUTE_KEYBOARD else "ComnCHAN"


def describe_port(code: int) -> str:
    """Meaning of a control's port code (record +18)."""
    if code & ROUTE_EXPLICIT:
        return port_mask_name(code)
    return "KeybPORT" if code & ROUTE_KEYBOARD else "ComnPORT"


def describe_template_channel(code: int) -> str:
    return f"ch {code + 1}" if code < 16 else f"code {code:02X} (unconfirmed)"


def describe_template_port(code: int) -> str:
    """Header port bytes: only explicit masks (bit 6 set) are confirmed."""
    if code & ROUTE_EXPLICIT:
        return port_mask_name(code)
    return f"code {code:02X} (unconfirmed)"


# Control types whose record uses the SysEx block (+26..+40).
SYSEX_TYPES = {"sysex", "template"}

SYSEX_DATA_TYPES: dict[int, str] = {0: "none", 1: "single"}


class ValidationError(ValueError):
    pass


def check_raw(label: str, raw: bytes, length: int) -> None:
    """Hand-edited ``_raw`` hex must keep its length and stay 7-bit, or the encoded
    message would not be valid SysEx."""
    if len(raw) != length:
        raise ValidationError(f"{label} must be {length} bytes, got {len(raw)}")
    bad = next((i for i, b in enumerate(raw) if b & 0x80), None)
    if bad is not None:
        raise ValidationError(f"{label} byte {bad} is 0x{raw[bad]:02X}; only 00..7F allowed")


def check_name(name: str, limit: int = NAME_LEN) -> None:
    if len(name) > limit:
        raise ValidationError(f"name {name!r} is longer than {limit} characters")
    bad = [c for c in name if not 0x20 <= ord(c) < 0x7F]
    if bad:
        raise ValidationError(f"name {name!r} has non-printable/non-ASCII characters {bad!r}")


def check_range(label: str, value: int, lo: int, hi: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
        raise ValidationError(f"{label} must be an integer {lo}..{hi}, got {value!r}")


@dataclass
class SysexSpec:
    data_type: int = 0
    length: int = 0
    data_position: int = 0
    data: list[int] = field(default_factory=list)  # up to 12 bytes, F0/F7 implied

    def validate(self, *, strict: bool = True) -> None:
        """``strict`` applies the manual's SysEx limits; the same bytes carry other data on
        non-SysEx controls, so there only the 7-bit range is checked."""
        lim = SYSEX_MAX if strict else 127
        check_range("sysex.data_type", self.data_type, 0, 127)
        check_range("sysex.length", self.length, 0, lim)
        check_range("sysex.data_position", self.data_position, 0, lim)
        if len(self.data) > SYSEX_MAX:
            raise ValidationError(f"sysex.data holds at most {SYSEX_MAX} bytes")
        for i, b in enumerate(self.data):
            check_range(f"sysex.data[{i}]", b, 0, 127)


@dataclass
class Control:
    slot: str
    name: str = ""
    type: str = "none"
    low: int = 0
    high: int = 127
    number: int = 0  # CC number, NRPN/RPN LSB
    number_msb: int = 0  # NRPN/RPN MSB
    channel: int = 0x40  # raw code, see FORMAT.md R19
    port: int = 0x47  # raw code, see FORMAT.md R18
    value: int = 0  # stored control value
    button_mode: str = "normal"
    display: int = 0
    step: int = 0
    sysex: SysexSpec = field(default_factory=SysexSpec)
    raw: bytes | None = None  # the original 41-byte record; unknown bytes come from here

    def validate(self) -> None:
        if self.slot not in SLOT_BY_KEY:
            raise ValidationError(f"unknown control slot {self.slot!r}")
        check_name(self.name)
        type_code(self.type)
        if self.button_mode not in BUTTON_MODE_CODES:
            raise ValidationError(f"{self.slot}: unknown button_mode {self.button_mode!r}")
        for label, v, hi in (
            ("low", self.low, 0x3FFF),
            ("high", self.high, 0x3FFF),
            ("value", self.value, 0x3FFF),
            ("number", self.number, 127),
            ("number_msb", self.number_msb, 127),
            ("channel", self.channel, 127),
            ("port", self.port, 127),
            ("display", self.display, 127),
            ("step", self.step, 127),
        ):
            check_range(f"{self.slot}.{label}", v, 0, hi)
        self.sysex.validate(strict=self.type in SYSEX_TYPES)
        if self.raw is not None:
            check_raw(f"{self.slot}._raw", self.raw, RECORD_LEN)

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "low": self.low,
            "high": self.high,
            "number": self.number,
            "number_msb": self.number_msb,
            "channel": self.channel,
            "port": self.port,
            "value": self.value,
            "button_mode": self.button_mode,
            "display": self.display,
            "step": self.step,
            "sysex": {
                "data_type": self.sysex.data_type,
                "length": self.sysex.length,
                "data_position": self.sysex.data_position,
                "data": list(self.sysex.data),
            },
        }
        if self.raw is not None:
            d["_raw"] = self.raw.hex(" ")
        return d

    @classmethod
    def from_json(cls, slot: str, d: dict[str, Any]) -> Control:
        sx = d.get("sysex") or {}
        raw = d.get("_raw")
        c = cls(
            slot=slot,
            name=d.get("name", ""),
            type=d.get("type", "none"),
            low=d.get("low", 0),
            high=d.get("high", 127),
            number=d.get("number", 0),
            number_msb=d.get("number_msb", 0),
            channel=d.get("channel", 0x40),
            port=d.get("port", 0x47),
            value=d.get("value", 0),
            button_mode=d.get("button_mode", "normal"),
            display=d.get("display", 0),
            step=d.get("step", 0),
            sysex=SysexSpec(
                data_type=sx.get("data_type", 0),
                length=sx.get("length", 0),
                data_position=sx.get("data_position", 0),
                data=list(sx.get("data", [])),
            ),
            raw=bytes.fromhex(raw) if raw else None,
        )
        c.validate()
        return c


ROUTING_ATTRS = ("keyboard_channel", "keyboard_port", "common_channel", "common_port")


@dataclass
class Template:
    name: str = ""
    slot: int = 1  # 1-based memory location as shown on the device (1..40)
    group_size: int = 0
    group_position: int = 0
    # Template-wide routing (header 99-102), raw codes: channel 0-based, port as a mask code
    keyboard_channel: int = DEFAULT_TEMPLATE_CHANNEL
    keyboard_port: int = DEFAULT_TEMPLATE_PORT
    common_channel: int = DEFAULT_TEMPLATE_CHANNEL
    common_port: int = DEFAULT_TEMPLATE_PORT
    controls: dict[str, Control] = field(default_factory=dict)
    header_raw: bytes | None = None  # bytes 0..418 of the original message
    trailer_raw: bytes | None = None  # bytes after the last record, F7 included

    def control(self, key: str) -> Control:
        if key not in self.controls:
            self.controls[key] = Control(slot=key)
        return self.controls[key]

    def validate(self) -> None:
        check_name(self.name, TEMPLATE_NAME_LEN)
        check_range("slot", self.slot, 1, NUM_SLOTS)
        check_range("group_size", self.group_size, 0, 127)
        check_range("group_position", self.group_position, 0, 127)
        for label in ROUTING_ATTRS:
            check_range(label, getattr(self, label), 0, 127)
        if self.header_raw is not None:
            h = self.header_raw
            if not h.startswith(TEMPLATE_PREFIX):
                raise ValidationError(
                    "_raw.header must start with F0 00 20 29 02 03 (a ReMOTE SL template)"
                )
            check_raw("_raw.header", h[1:], HEADER_LEN - 1)
        if self.trailer_raw is not None:
            tr = self.trailer_raw
            if tr[-1:] != b"\xf7":
                raise ValidationError("_raw.trailer must end with F7")
            check_raw("_raw.trailer", tr[:-1], TRAILER_LEN - 1)
        for key, c in self.controls.items():
            if key != c.slot:
                raise ValidationError(f"control key {key!r} != slot {c.slot!r}")
            c.validate()

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "format": "slcfg-template/1",
            "name": self.name,
            "slot": self.slot,
            "group": {"size": self.group_size, "position": self.group_position},
            "routing": {
                "keyboard": {"channel": self.keyboard_channel, "port": self.keyboard_port},
                "common": {"channel": self.common_channel, "port": self.common_port},
            },
            "controls": {
                s.key: self.controls[s.key].to_json() for s in SLOTS if s.key in self.controls
            },
        }
        raw: dict[str, str] = {}
        if self.header_raw is not None:
            raw["header"] = self.header_raw.hex(" ")
        if self.trailer_raw is not None:
            raw["trailer"] = self.trailer_raw.hex(" ")
        if raw:
            d["_raw"] = raw
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Template:
        fmt = d.get("format", "slcfg-template/1")
        if fmt != "slcfg-template/1":
            raise ValidationError(f"unsupported format {fmt!r}")
        raw = d.get("_raw") or {}
        group = d.get("group") or {}
        header_raw = bytes.fromhex(raw["header"]) if "header" in raw else None
        routing = d.get("routing") or {}

        def route(section: str, key: str, offset: int, default: int) -> int:
            # files written before routing was decoded: keep what the raw header holds
            if key in (routing.get(section) or {}):
                return routing[section][key]
            if header_raw is not None and len(header_raw) > offset:
                return header_raw[offset]
            return default

        t = cls(
            name=d.get("name", ""),
            slot=d.get("slot", 1),
            group_size=group.get("size", 0),
            group_position=group.get("position", 0),
            keyboard_channel=route(
                "keyboard", "channel", KEYBOARD_CHANNEL_OFFSET, DEFAULT_TEMPLATE_CHANNEL
            ),
            keyboard_port=route("keyboard", "port", KEYBOARD_PORT_OFFSET, DEFAULT_TEMPLATE_PORT),
            common_channel=route(
                "common", "channel", COMMON_CHANNEL_OFFSET, DEFAULT_TEMPLATE_CHANNEL
            ),
            common_port=route("common", "port", COMMON_PORT_OFFSET, DEFAULT_TEMPLATE_PORT),
            controls={k: Control.from_json(k, v) for k, v in (d.get("controls") or {}).items()},
            header_raw=header_raw,
            trailer_raw=bytes.fromhex(raw["trailer"]) if "trailer" in raw else None,
        )
        t.validate()
        return t
