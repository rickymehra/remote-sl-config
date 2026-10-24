import json

import pytest

from conftest import BULK, COMMUNITY
from slcfg import codec
from slcfg.model import SLOTS, Control, Template, ValidationError


def test_community_dumps_present():
    assert len(COMMUNITY) >= 90


@pytest.mark.parametrize("path", COMMUNITY, ids=lambda p: p.name)
def test_roundtrip_every_community_dump(path):
    """Required: encode(decode(x)) == x for every community dump, also through JSON."""
    data = path.read_bytes()
    templates = codec.decode_file(data)
    assert codec.encode_file(templates) == data
    via_json = [Template.from_json(json.loads(json.dumps(t.to_json()))) for t in templates]
    assert codec.encode_file(via_json) == data


def test_bulk_dump_has_40_templates():
    ts = codec.decode_file(BULK.read_bytes())
    assert len(ts) == 40
    assert [t.slot for t in ts] == list(range(1, 41))
    assert all(codec.is_bulk(t) for t in ts)
    assert ts[39].name.startswith("Ableton Live Automap")


def test_vstation_fields(vstation):
    t = codec.decode(vstation)
    assert t.name.startswith("V-Station-1") and t.name.endswith("Novation")
    assert (t.slot, t.group_size, t.group_position) == (1, 3, 1)
    assert not codec.is_bulk(t)
    semi = t.controls["encoder_2"]
    assert (semi.name, semi.type, semi.number, semi.display) == ("Osc1Semi", "cc", 40, 1)
    wave = t.controls["encoder_3"]
    assert (wave.type, wave.low, wave.high, wave.number) == ("nrpn", 4, 7, 0x69)
    arp = t.controls["button_row3_1"]
    assert (arp.name, arp.button_mode) == ("ArpOnOff", "toggle")
    octv = t.controls["button_row1_1"]
    assert octv.button_mode == "step"
    assert t.controls["expression"].number == 11
    assert t.controls["sustain"].number == 64
    assert t.controls["mod"].number == 1
    assert t.controls["pitch"].type == "pitch_bend"
    assert t.controls["rewind"].type == "mmc" and t.controls["rewind"].low == 5


def test_tx802_sysex_record():
    path = next(p for p in COMMUNITY if p.name == "TX802_3.syx")
    t = codec.decode(path.read_bytes())
    algo = t.controls["encoder_1"]
    assert algo.type == "sysex"
    assert (algo.sysex.data_type, algo.sysex.length, algo.sysex.data_position) == (1, 5, 5)
    assert algo.sysex.data == [0x43, 0x10, 0x01, 0x06, 0x7F]
    pad = t.controls["drum_pad_2"]
    assert pad.type == "template" and pad.low == 2


def test_edit_changes_only_expected_bytes(vstation):
    t = codec.decode(vstation)
    c = t.controls["encoder_1"]
    c.name = "Cutoff"
    c.number = 74
    out = codec.encode(t)
    changed = [i for i, (a, b) in enumerate(zip(vstation, out, strict=True)) if a != b]
    base = codec.RECORD_BASE
    assert changed == [
        base + 0,
        base + 1,
        base + 2,
        base + 3,
        base + 4,
        base + 5,
        base + 6,
        base + 7,
        base + 17,
    ]
    assert codec.decode(out).controls["encoder_1"].name == "Cutoff"


def test_button_mode_keeps_other_bits():
    rec = bytearray(codec.DEFAULT_RECORD)
    rec[13] = 0x09  # unknown bit 0 + toggle, as seen on many factory buttons
    c = codec.decode_control(SLOTS[24], bytes(rec))
    assert c.button_mode == "toggle"
    c.button_mode = "step"
    out = codec.encode_control(c)
    assert out[13] == 0x11


def test_new_template_from_scratch():
    t = Template(name="My synth", slot=12)
    c = t.control("slider_1")
    c.name, c.type, c.number = "Cutoff", "cc", 74
    data = codec.encode(t)
    assert len(data) == codec.MESSAGE_LEN
    back = codec.decode(data)
    assert (back.name, back.slot) == ("My synth", 12)
    assert back.controls["slider_1"].number == 74
    assert back.controls["encoder_1"].type == "none"


def test_sysex_edit_pads_buffer(vstation):
    t = codec.decode(vstation)
    c = t.controls["pot_1"]
    c.type = "sysex"
    c.sysex.data_type, c.sysex.length, c.sysex.data_position = 1, 3, 3
    c.sysex.data = [0x7D, 0x01, 0x7F]
    rec = codec.encode_control(c)
    assert rec[26:32] == bytes([1, 3, 3, 0x7D, 0x01, 0x7F])
    assert rec[32:41] == bytes(9)


def test_decode_errors():
    with pytest.raises(codec.CodecError):
        codec.decode(b"\xf0\xf7")
    with pytest.raises(codec.CodecError):
        codec.decode(bytes([0xF0, 0x41]) + bytes(4109) + b"\xf7")
    with pytest.raises(codec.CodecError):
        codec.decode_file(b"")
    with pytest.raises(codec.CodecError):
        codec.decode_file(b"\x00")


def test_validation_blocks_bad_values(vstation):
    t = codec.decode(vstation)
    t.controls["encoder_1"].name = "TooLongName"
    with pytest.raises(ValidationError):
        codec.encode(t)
    t.controls["encoder_1"].name = "ok"
    t.controls["encoder_1"].number = 128
    with pytest.raises(ValidationError):
        codec.encode(t)


def test_offset_table_is_consistent():
    for fields, limit in (
        (codec.RECORD_FIELDS, codec.RECORD_LEN),
        (codec.HEADER_FIELDS, codec.RECORD_BASE),
    ):
        spans = sorted((f.offset, f.offset + f.size) for f in fields)
        assert all(end <= limit for _, end in spans)
        assert all(
            a_end <= b_start for (_, a_end), (b_start, _) in zip(spans, spans[1:], strict=False)
        )
        assert {f.confidence for f in fields} <= {"confirmed", "likely", "guess"}
    assert len(SLOTS) == 90
    assert Control(slot="encoder_1").to_json()["type"] == "none"
