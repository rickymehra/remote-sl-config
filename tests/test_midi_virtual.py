"""End-to-end MIDI through the real mido/python-rtmidi stack, against virtual ports.

A pair of virtual ports plays the SL: whatever we send is recorded, and it can dump
templates back. This exercises MidoPort, the OS MIDI layer and large SysEx handling;
it says nothing about how the real SL behaves.

Virtual ports need CoreMIDI (macOS) or an ALSA sequencer (Linux desktop). Elsewhere the
tests skip, unless SLCFG_REQUIRE_VIRTUAL_MIDI=1 (set on the macOS CI job) makes that a
failure, so they can never be skipped silently where they should run.
"""

import os
import threading
import time

import pytest
from typer.testing import CliRunner

from conftest import BULK, V_STATION_1
from slcfg import midi_io
from slcfg.cli import app
from slcfg.sysex import split_messages

NAME = "slcfg virtual SL"


class VirtualSL:
    """Virtual input+output ports named NAME, acting as the keyboard."""

    def __init__(self) -> None:
        import mido

        self.mido = mido
        self.received: list[bytes] = []
        self._lock = threading.Lock()
        # our "MIDI out" (what slcfg opens as output) is this virtual input, and vice versa
        self.inport = mido.open_input(NAME, virtual=True, callback=self._on_message)
        self.outport = mido.open_output(NAME, virtual=True)
        self._dumper: threading.Timer | None = None

    def _on_message(self, msg) -> None:
        if msg.type == "sysex":
            with self._lock:
                self.received.append(bytes([0xF0, *msg.data, 0xF7]))

    def dump_later(self, delay: float, data: bytes) -> None:
        """Dump from a background thread after ``delay`` seconds; close() waits for it."""
        self._dumper = threading.Timer(delay, self.dump, args=(data,))
        self._dumper.start()

    def dump(self, data: bytes, gap: float = 0.02) -> None:
        for m in split_messages(data):
            self.outport.send(self.mido.Message("sysex", data=list(m.payload)))
            time.sleep(gap)

    def wait_received(self, n: int, timeout: float = 15.0) -> list[bytes]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if len(self.received) >= n:
                    return list(self.received)
            time.sleep(0.02)
        return list(self.received)

    def close(self) -> None:
        # a dump still sending into a closed port crashes python-rtmidi
        if self._dumper is not None:
            self._dumper.join()
        # detach the callback and let an in-flight one finish first (see MidoPort.close)
        self.inport.callback = None
        time.sleep(0.05)
        self.inport.close()
        self.outport.close()


@pytest.fixture
def sl():
    try:
        dev = VirtualSL()
    except Exception as e:  # rtmidi raises SystemError/RuntimeError without a MIDI system
        if os.environ.get("SLCFG_REQUIRE_VIRTUAL_MIDI") == "1":
            pytest.fail(f"virtual MIDI ports required but unavailable: {e}")
        pytest.skip(f"no virtual MIDI ports here: {e}")
    time.sleep(0.2)  # let the OS publish the new ports
    yield dev
    dev.close()


def test_send_template_over_virtual_port(sl):
    data = V_STATION_1.read_bytes()
    port = midi_io.MidoPort(NAME)
    try:
        assert midi_io.send_template(port, data, lambda s: True) == 1
    finally:
        port.close()
    assert sl.wait_received(1) == [data]  # 4112-byte SysEx arrives intact


def test_receive_full_dump_over_virtual_port(sl):
    """Templates that arrive must be intact and in order. Completeness is not checked:
    on macOS CI, CoreMIDI drops whole messages sent from a virtual source (up to ~45% of
    a 40-template dump, at any pacing and from another process too) before python-rtmidi
    sees them; see DECISIONS.md 43. test_send_full_dump_over_virtual_port is strict."""
    data = BULK.read_bytes()
    expected = [m.data for m in split_messages(data)]
    port = midi_io.MidoPort(NAME)
    try:
        sl.dump_later(0.3, data)
        got = midi_io.receive_dump(port, timeout=20, count=40)
    finally:
        port.close()
    assert got, "nothing arrived"
    it = iter(expected)
    assert all(m in it for m in got)  # each one byte-identical, in dump order
    print(f"received {len(got)}/40")


def test_send_full_dump_over_virtual_port(sl):
    data = BULK.read_bytes()
    port = midi_io.MidoPort(NAME)
    try:
        assert midi_io.send_template(port, data, lambda s: True, gap=0.02) == 40
    finally:
        port.close()
    assert sl.wait_received(40) == [m.data for m in split_messages(data)]


def test_cli_send_and_receive_with_device(sl, tmp_path):
    runner = CliRunner()
    r = runner.invoke(app, ["send", str(V_STATION_1), "--device", NAME], input="y\n")
    assert r.exit_code == 0, r.output
    assert sl.wait_received(1) == [V_STATION_1.read_bytes()]

    out = tmp_path / "dump.syx"
    # three copies: CoreMIDI may drop one from a virtual source (see the dump test above)
    sl.dump_later(0.5, V_STATION_1.read_bytes() * 3)
    r = runner.invoke(app, ["receive", "--device", NAME, "-o", str(out), "--timeout", "15"])
    assert r.exit_code == 0, r.output
    assert out.read_bytes() == V_STATION_1.read_bytes()


def test_partial_port_name_matches(sl):
    port = midi_io.MidoPort("virtual sl")  # case-insensitive part of the name
    try:
        assert NAME in port.name
    finally:
        port.close()
