"""Regenerate the synthetic .syx fixtures: ``uv run python tests/fixtures/make_fixtures.py``.

They are made from scratch (no community data) so the analysis tools can be tested on
inputs whose structure is known exactly.
"""

from pathlib import Path

HERE = Path(__file__).parent


def records_message(stride: int, count: int, *, base: int = 20) -> bytes:
    """A Novation-framed message with ``count`` fixed-size records, each starting with an
    8-char label followed by small varying numbers."""
    head = bytes([0xF0, 0x00, 0x20, 0x29, 0x7D, 0x01]) + bytes(base - 6)
    body = bytearray()
    for i in range(count):
        rec = bytearray(stride)
        rec[:8] = f"Ctl {i:02d}  ".encode()[:8]
        rec[8] = 1
        rec[9] = i % 128
        rec[10] = 0x7F
        body += rec
    return head + bytes(body) + b"\xf7"


def main() -> None:
    a = records_message(24, 16)
    b = bytearray(a)
    b[20 + 24 * 3 + 9] = 0x40  # record 3, field +9 changed
    (HERE / "stride24_a.syx").write_bytes(a)
    (HERE / "stride24_b.syx").write_bytes(bytes(b))
    two = bytes([0xF0, 0x43, 0x10, 0x01, 0x06, 0x05, 0xF7]) + records_message(41, 10)
    (HERE / "two_messages.syx").write_bytes(two)


if __name__ == "__main__":
    main()
