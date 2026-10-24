"""Low-level SysEx helpers: message splitting, manufacturer IDs and data encodings.

Nothing here is specific to the ReMOTE SL template layout; see ``codec.py`` for that.
"""

from __future__ import annotations

from dataclasses import dataclass

SOX = 0xF0
EOX = 0xF7
NOVATION_ID = bytes([0x00, 0x20, 0x29])

# A few manufacturer IDs that show up in community dumps (embedded SysEx strings).
MANUFACTURERS: dict[bytes, str] = {
    NOVATION_ID: "Novation",
    bytes([0x43]): "Yamaha",
    bytes([0x41]): "Roland",
    bytes([0x42]): "Korg",
    bytes([0x7D]): "Non-commercial",
    bytes([0x7E]): "Universal non-realtime",
    bytes([0x7F]): "Universal realtime",
}


class SysexError(ValueError):
    """Raised for malformed SysEx data."""


@dataclass(frozen=True)
class Message:
    """One F0 ... F7 message found in a byte stream."""

    offset: int
    data: bytes

    @property
    def manufacturer_id(self) -> bytes:
        return manufacturer_id(self.data)

    @property
    def manufacturer(self) -> str:
        return MANUFACTURERS.get(self.manufacturer_id, "unknown")

    @property
    def payload(self) -> bytes:
        """Bytes between F0 and F7."""
        return self.data[1:-1]


def manufacturer_id(msg: bytes) -> bytes:
    """Return the 1- or 3-byte manufacturer ID of a SysEx message (which starts with F0)."""
    if len(msg) < 2 or msg[0] != SOX:
        raise SysexError("not a SysEx message")
    if msg[1] == 0x00:
        if len(msg) < 4:
            raise SysexError("truncated 3-byte manufacturer ID")
        return bytes(msg[1:4])
    return bytes(msg[1:2])


def split_messages(data: bytes, *, strict: bool = True) -> list[Message]:
    """Split a .syx byte stream into messages.

    With ``strict`` (default) any byte outside F0..F7 framing, or a message missing its F7,
    raises :class:`SysexError`. Non-strict mode skips stray bytes.
    """
    out: list[Message] = []
    i = 0
    n = len(data)
    while i < n:
        if data[i] != SOX:
            if strict:
                raise SysexError(f"stray byte 0x{data[i]:02X} at offset {i}")
            i += 1
            continue
        j = data.find(EOX, i + 1)
        if j < 0:
            if strict:
                raise SysexError(f"unterminated message at offset {i}")
            break
        body = data[i + 1 : j]
        bad = next((k for k, b in enumerate(body) if b & 0x80), None)
        if bad is not None and strict:
            raise SysexError(f"status byte 0x{body[bad]:02X} inside message at {i + 1 + bad}")
        out.append(Message(i, bytes(data[i : j + 1])))
        i = j + 1
    return out


# --- MIDI 8-to-7 packing ----------------------------------------------------------------
# Common scheme (Roland/Korg/Novation firmware): each group of 7 data bytes is preceded by
# one byte holding their stripped MSBs, bit k = MSB of byte k.


def pack_7bit(data: bytes) -> bytes:
    """Pack arbitrary 8-bit data into 7-bit-safe bytes (8 output bytes per 7 input)."""
    out = bytearray()
    for i in range(0, len(data), 7):
        chunk = data[i : i + 7]
        msbs = 0
        for k, b in enumerate(chunk):
            msbs |= ((b >> 7) & 1) << k
        out.append(msbs)
        out.extend(b & 0x7F for b in chunk)
    return bytes(out)


def unpack_7bit(data: bytes) -> bytes:
    """Inverse of :func:`pack_7bit`. A trailing partial group is decoded as far as it goes."""
    out = bytearray()
    for i in range(0, len(data), 8):
        msbs = data[i]
        for k, b in enumerate(data[i + 1 : i + 8]):
            out.append((b & 0x7F) | (((msbs >> k) & 1) << 7))
    return bytes(out)


# --- Nibblized data (one byte split over two 4-bit bytes) -----------------------------------


def nibblize(data: bytes, *, low_first: bool = True) -> bytes:
    out = bytearray()
    for b in data:
        lo, hi = b & 0x0F, b >> 4
        out.extend((lo, hi) if low_first else (hi, lo))
    return bytes(out)


def denibblize(data: bytes, *, low_first: bool = True) -> bytes:
    """Join pairs of nibble bytes. An odd trailing byte is dropped."""
    out = bytearray()
    for i in range(0, len(data) - 1, 2):
        a, b = data[i] & 0x0F, data[i + 1] & 0x0F
        out.append((b << 4 | a) if low_first else (a << 4 | b))
    return bytes(out)


# --- 14-bit values as stored by the SL (two 7-bit bytes) --------------------------------------


def u14_be(msb: int, lsb: int) -> int:
    return ((msb & 0x7F) << 7) | (lsb & 0x7F)


def split_u14_be(value: int) -> tuple[int, int]:
    if not 0 <= value <= 0x3FFF:
        raise ValueError(f"14-bit value out of range: {value}")
    return value >> 7, value & 0x7F


VIEWS = ("raw", "unpacked7", "nibble")


def view(data: bytes, mode: str) -> bytes:
    """Return ``data`` transformed into one of the alternate :data:`VIEWS`."""
    if mode == "raw":
        return data
    if mode == "unpacked7":
        return unpack_7bit(data)
    if mode == "nibble":
        return denibblize(data)
    raise ValueError(f"unknown view {mode!r}; choose from {VIEWS}")
