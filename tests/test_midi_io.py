import pytest

from slcfg import midi_io


def test_send_requires_confirmation(vstation):
    port = midi_io.FakeMidiPort()
    seen = []
    with pytest.raises(midi_io.SendCancelled):
        midi_io.send_template(port, vstation, lambda s: seen.append(s) or False)
    assert port.sent == []
    assert "4112 bytes" in seen[0]
    assert "own risk" in seen[0] and "UNTESTED" in seen[0]
    # truthy-but-not-True answers do not count as a confirmation
    with pytest.raises(midi_io.SendCancelled):
        midi_io.send_template(port, vstation, lambda s: "yes")
    assert midi_io.send_template(port, vstation, lambda s: True) == 1
    assert port.sent == [vstation]


def test_fake_port_rejects_non_sysex():
    port = midi_io.FakeMidiPort()
    with pytest.raises(midi_io.MidiIOError):
        port.send(b"\x90\x40\x7f")
    with pytest.raises(midi_io.MidiIOError):
        port.send(b"\xf0\x80\xf7")
    port.close()
    with pytest.raises(midi_io.MidiIOError):
        port.send(b"\xf0\x7d\xf7")


def test_receive_dump_and_loopback(vstation):
    port = midi_io.FakeMidiPort(inbox=[vstation])
    assert midi_io.receive_dump(port, timeout=0.1) == [vstation]
    assert midi_io.receive_dump(port, timeout=0.1) == []
    port.echo = True
    midi_io.send_template(port, vstation, lambda s: True)
    assert midi_io.receive_dump(port, timeout=0.1) == [vstation]


def test_open_port_defaults_to_fake():
    port = midi_io.open_port(None)
    assert isinstance(port, midi_io.FakeMidiPort)
    assert isinstance(port, midi_io.MidiPort)


def test_progress_callbacks():
    from conftest import BULK
    from slcfg.sysex import split_messages

    data = BULK.read_bytes()
    port = midi_io.FakeMidiPort()
    seen = []
    assert (
        midi_io.send_template(port, data, lambda s: True, progress=lambda d, t: seen.append((d, t)))
        == 40
    )
    assert seen[0] == (1, 40) and seen[-1] == (40, 40) and len(seen) == 40
    port = midi_io.FakeMidiPort(inbox=[m.data for m in split_messages(data)])
    got = []
    midi_io.receive_dump(port, count=40, timeout=1, progress=lambda d, t: got.append(d))
    assert got == list(range(1, 41))


def test_receive_can_be_cancelled():
    import threading

    cancel = threading.Event()
    cancel.set()
    port = midi_io.FakeMidiPort(inbox=[b"\xf0\x7d\xf7"])
    assert midi_io.receive_dump(port, count=1, timeout=5, cancel=cancel) == []


def test_resolve_port_name():
    names = ["ReMOTE SL:ReMOTE SL MIDI 1 20:0", "ReMOTE SL:ReMOTE SL MIDI 2 20:1", "IAC Bus 1"]
    assert midi_io.resolve_port_name("IAC Bus 1", names) == "IAC Bus 1"
    assert midi_io.resolve_port_name("midi 1", names) == names[0]
    with pytest.raises(midi_io.MidiIOError, match="several"):
        midi_io.resolve_port_name("ReMOTE", names)
    with pytest.raises(midi_io.MidiIOError, match="available: 'ReMOTE"):
        midi_io.resolve_port_name("Launchpad", names)


def test_mido_port_reports_missing_device():
    with pytest.raises(midi_io.MidiIOError):
        midi_io.MidoPort("no such device 12345")


def test_sysex_assembler_rebuilds_messages_from_any_chunking(vstation):
    a, b = vstation, vstation[:-3] + b"\x00\x00\xf7"
    stream = b"\x90\x40\x7f" + a + b"\xf8" + b  # note-on before, clock byte between
    for size in (1, 7, 256, 4112, 5000, len(stream)):
        asm = midi_io.SysexAssembler()
        got = []
        for i in range(0, len(stream), size):
            got += asm.feed(stream[i : i + size])
        assert got == [a, b], size


def test_sysex_assembler_drops_interrupted_message():
    asm = midi_io.SysexAssembler()
    assert asm.feed(b"\xf0\x7d\x01\x90\x40\x7f\x02\xf7") == []  # cut off by a note-on
    assert asm.feed(b"\xf0\x7d\x01\xf0\x7d\x02\xf7") == [b"\xf0\x7d\x02\xf7"]  # restarted
    assert asm.feed(b"\xf8") == []
