import pytest

from slcfg.sysex import (
    SysexError,
    denibblize,
    manufacturer_id,
    nibblize,
    pack_7bit,
    split_messages,
    split_u14_be,
    u14_be,
    unpack_7bit,
    view,
)


def test_split_two_messages(fixtures):
    msgs = split_messages((fixtures / "two_messages.syx").read_bytes())
    assert [len(m.data) for m in msgs] == [7, 20 + 41 * 10 + 1]
    assert msgs[0].manufacturer == "Yamaha"
    assert msgs[1].manufacturer_id == bytes([0x00, 0x20, 0x29])
    assert msgs[1].manufacturer == "Novation"
    assert msgs[1].offset == 7


def test_split_rejects_garbage():
    with pytest.raises(SysexError):
        split_messages(b"\x01\xf0\x7d\xf7")
    with pytest.raises(SysexError):
        split_messages(b"\xf0\x7d\x01")
    with pytest.raises(SysexError):
        split_messages(b"\xf0\x7d\x90\xf7")
    assert len(split_messages(b"\x01\xf0\x7d\xf7", strict=False)) == 1


def test_manufacturer_id_lengths():
    assert manufacturer_id(b"\xf0\x41\x10\xf7") == b"\x41"
    assert manufacturer_id(b"\xf0\x00\x20\x29\xf7") == b"\x00\x20\x29"
    with pytest.raises(SysexError):
        manufacturer_id(b"\x90")


@pytest.mark.parametrize("data", [b"", b"\x00", bytes(range(256)), b"\xff" * 15])
def test_pack_unpack_roundtrip(data):
    packed = pack_7bit(data)
    assert all(b < 0x80 for b in packed)
    assert unpack_7bit(packed) == data


def test_pack_layout():
    # MSB byte first, bit k = MSB of byte k
    assert pack_7bit(bytes([0x80, 0x01, 0xFF])) == bytes([0b101, 0x00, 0x01, 0x7F])


def test_nibble_roundtrip():
    data = bytes([0x12, 0xAB, 0x00, 0xFF])
    assert nibblize(data) == bytes([2, 1, 0xB, 0xA, 0, 0, 0xF, 0xF])
    assert denibblize(nibblize(data)) == data
    assert denibblize(nibblize(data, low_first=False), low_first=False) == data


def test_u14():
    assert u14_be(0x7F, 0x7F) == 16383
    assert split_u14_be(300) == (2, 44)
    with pytest.raises(ValueError):
        split_u14_be(16384)


def test_view_unknown():
    assert view(b"\x01", "raw") == b"\x01"
    with pytest.raises(ValueError):
        view(b"", "bogus")
