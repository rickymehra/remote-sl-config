from slcfg.diff import ByteDiff, diff_bytes, diff_views, format_diff


def test_diff_finds_single_change(fixtures):
    a = (fixtures / "stride24_a.syx").read_bytes()
    b = (fixtures / "stride24_b.syx").read_bytes()
    d = diff_bytes(a, b)
    assert d == [ByteDiff(20 + 24 * 3 + 9, 3, 0x40)]
    text = format_diff(d, record_base=20, stride=24)
    assert "r03+09" in text
    assert "03    3  ." in text and "40   64  @" in text


def test_diff_length_overhang():
    d = diff_bytes(b"ab", b"abcd")
    assert d == [ByteDiff(2, None, ord("c")), ByteDiff(3, None, ord("d"))]
    assert diff_bytes(b"abc", b"a") == [ByteDiff(1, ord("b"), None), ByteDiff(2, ord("c"), None)]
    assert "--  ---  -" in format_diff(d)


def test_diff_views():
    from slcfg.sysex import nibblize, pack_7bit

    a, b = bytes([0x10, 0x20]), bytes([0x10, 0xA0])
    assert diff_views(pack_7bit(a), pack_7bit(b), "unpacked7") == [ByteDiff(1, 0x20, 0xA0)]
    assert diff_views(nibblize(a), nibblize(b), "nibble") == [ByteDiff(1, 0x20, 0xA0)]
    # skip shifts raw offsets back to file positions
    assert diff_views(b"\x00\x01\x02", b"\x00\x01\x03", "raw", skip=1) == [ByteDiff(2, 2, 3)]
