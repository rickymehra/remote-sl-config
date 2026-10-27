import pytest

from slcfg.model import (
    BUTTON_MODES,
    SLOT_BY_INDEX,
    SLOT_BY_KEY,
    Control,
    SysexSpec,
    Template,
    ValidationError,
    type_code,
    type_name,
)


def test_slot_table_covers_every_control():
    groups = {}
    for s in SLOT_BY_KEY.values():
        groups[s.group] = groups.get(s.group, 0) + 1
    assert groups == {
        "encoder": 8,
        "pot": 8,
        "slider": 8,
        "button_row1": 8,
        "button_row2": 8,
        "button_row3": 8,
        "button_row4": 8,
        "drum_pad": 8,
        "pedal": 2,
        "joystick": 2,
        "touchpad": 4,
        "transport": 6,
        "extra": 12,
    }
    assert SLOT_BY_INDEX[67].key == "pitch" and SLOT_BY_INDEX[77].key == "loop"


def test_type_names_roundtrip():
    assert type_code(type_name(1)) == 1
    assert type_name(99) == "type_99" and type_code("type_99") == 99
    with pytest.raises(ValidationError):
        type_code("bogus")


def test_button_modes_cover_all_codes():
    assert len(BUTTON_MODES) == 8 and BUTTON_MODES[8] == "toggle"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "123456789"},
        {"name": "café"},
        {"low": -1},
        {"high": 16384},
        {"channel": 128},
        {"button_mode": "sticky"},
        {"slot": "nope"},
    ],
)
def test_control_validation(kwargs):
    c = Control(slot="encoder_1")
    for k, v in kwargs.items():
        setattr(c, k, v)
    with pytest.raises(ValidationError):
        c.validate()


def test_sysex_limits_only_for_sysex_types():
    c = Control(slot="encoder_1", type="cc", sysex=SysexSpec(length=19))
    c.validate()
    c.type = "sysex"
    with pytest.raises(ValidationError):
        c.validate()
    with pytest.raises(ValidationError):
        SysexSpec(data=[0] * 13).validate()


def test_template_validation_and_json():
    t = Template(name="x" * 48, slot=40)
    t.control("pot_3").name = "Res"
    t.validate()
    again = Template.from_json(t.to_json())
    assert again.controls["pot_3"].name == "Res"
    with pytest.raises(ValidationError):
        Template.from_json({**t.to_json(), "slot": 41})
    with pytest.raises(ValidationError):
        Template.from_json({**t.to_json(), "format": "other/9"})
    t.controls["pot_3"].slot = "pot_4"
    with pytest.raises(ValidationError):
        t.validate()


@pytest.mark.parametrize(
    "edit",
    [
        lambda h, r, t: (h[:20] + b"\xf7" + h[21:], r, t),  # 8-bit byte in the header
        lambda h, r, t: (b"\xf0\x41" + h[2:], r, t),  # not a Novation SL header
        lambda h, r, t: (h[:-1], r, t),  # header one byte short
        lambda h, r, t: (h, r[:30] + b"\xf0" + r[31:], t),  # 8-bit byte in a record
        lambda h, r, t: (h, r + b"\x00", t),  # record one byte long
        lambda h, r, t: (h, r, b"\x92\x34\xf7"),  # 8-bit byte in the trailer
        lambda h, r, t: (h, r, b"\x12\x34\x00"),  # trailer without F7
        lambda h, r, t: (h, r, b"\x12\x34\xf7\x00"),  # trailer too long
    ],
)
def test_hand_edited_raw_bytes_are_rejected(vstation, edit):
    """`_raw` hex edited by hand must not encode into an invalid SysEx file."""
    from slcfg import codec

    d = codec.decode(vstation).to_json()
    h = bytes.fromhex(d["_raw"]["header"])
    r = bytes.fromhex(d["controls"]["encoder_1"]["_raw"])
    t = bytes.fromhex(d["_raw"]["trailer"])
    h, r, t = edit(h, r, t)
    d["_raw"] = {"header": h.hex(" "), "trailer": t.hex(" ")}
    d["controls"]["encoder_1"]["_raw"] = r.hex(" ")
    with pytest.raises(ValidationError):
        Template.from_json(d)
