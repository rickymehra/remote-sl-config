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

    def _on_message(self, msg) -> None:
        if msg.type == "sysex":
            with self._lock:
                self.received.append(bytes([0xF0, *msg.data, 0xF7]))

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


class RecordingAssembler(midi_io.SysexAssembler):
    """Keeps every raw input chunk so a failure can say where bytes went missing."""

    chunks: list[bytes] = []

    def feed(self, chunk: bytes) -> list[bytes]:
        RecordingAssembler.chunks.append(bytes(chunk))
        return super().feed(chunk)


@pytest.mark.parametrize("attempt", range(8))  # TEMP: measure how often templates go missing
def test_receive_full_dump_over_virtual_port(sl, monkeypatch, attempt):
    data = BULK.read_bytes()
    RecordingAssembler.chunks = []
    monkeypatch.setattr(midi_io, "SysexAssembler", RecordingAssembler)
    port = midi_io.MidoPort(NAME)
    try:
        threading.Timer(0.3, sl.dump, args=(data,)).start()
        got = midi_io.receive_dump(port, timeout=30, count=40)
    finally:
        port.close()
    raw = b"".join(RecordingAssembler.chunks)
    sizes = sorted({len(c) for c in RecordingAssembler.chunks})
    report = (
        f"got {len(got)} messages; raw input {len(raw)} of {len(data)} bytes in "
        f"{len(RecordingAssembler.chunks)} chunks (sizes {sizes[:5]}..{sizes[-5:]}), "
        f"{raw.count(0xF0)} F0 and {raw.count(0xF7)} F7 bytes; "
        f"lengths {[len(m) for m in got if len(m) != 4112]} not 4112"
    )
    print(report)
    assert len(got) == 40, report
    assert b"".join(got) == data


def test_cli_send_and_receive_with_device(sl, tmp_path):
    runner = CliRunner()
    r = runner.invoke(app, ["send", str(V_STATION_1), "--device", NAME], input="y\n")
    assert r.exit_code == 0, r.output
    assert sl.wait_received(1) == [V_STATION_1.read_bytes()]

    out = tmp_path / "dump.syx"
    threading.Timer(0.5, sl.dump, args=(V_STATION_1.read_bytes(),)).start()
    r = runner.invoke(app, ["receive", "--device", NAME, "-o", str(out), "--timeout", "15"])
    assert r.exit_code == 0, r.output
    assert out.read_bytes() == V_STATION_1.read_bytes()


def test_partial_port_name_matches(sl):
    port = midi_io.MidoPort("virtual sl")  # case-insensitive part of the name
    try:
        assert NAME in port.name
    finally:
        port.close()


# TEMP experiment: where do templates go missing? -------------------------------------
import subprocess  # noqa: E402
import sys  # noqa: E402

_SENDER = r"""
import sys, time, mido
from slcfg.sysex import split_messages
name, path, gap = sys.argv[1], sys.argv[2], float(sys.argv[3])
out = mido.open_output(name, virtual=True)
inp = mido.open_input(name, virtual=True)
print("ready", flush=True)
sys.stdin.readline()
for m in split_messages(open(path, "rb").read()):
    out.send(mido.Message("sysex", data=list(m.payload)))
    time.sleep(gap)
print("sent", flush=True)
sys.stdin.readline()
"""
RESULTS: list[str] = []


@pytest.mark.parametrize(
    "mode,gap",
    [("thread", 0.02)] * 6 + [("thread", 0.1)] * 6 + [("process", 0.02)] * 6,
)
def test_experiment_dump_loss(mode, gap):
    if os.environ.get("SLCFG_REQUIRE_VIRTUAL_MIDI") != "1":
        pytest.skip("macOS CI only")
    data = BULK.read_bytes()
    if mode == "thread":
        dev = VirtualSL()
        time.sleep(0.2)
        port = midi_io.MidoPort(NAME)
        try:
            threading.Timer(0.3, dev.dump, args=(data, gap)).start()
            got = midi_io.receive_dump(port, timeout=20, count=40)
        finally:
            port.close()
            dev.close()
    else:
        name = "slcfg proc SL"
        p = subprocess.Popen(
            [sys.executable, "-c", _SENDER, name, str(BULK), str(gap)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        assert p.stdout.readline().strip() == "ready"
        time.sleep(0.3)
        port = midi_io.MidoPort(name)
        try:
            p.stdin.write("go\n")
            p.stdin.flush()
            got = midi_io.receive_dump(port, timeout=20, count=40)
        finally:
            port.close()
            p.stdin.write("quit\n")
            p.stdin.flush()
            p.wait(10)
    RESULTS.append(f"{mode} gap={gap}: {len(got)}/40")


def test_experiment_zz_report():
    if os.environ.get("SLCFG_REQUIRE_VIRTUAL_MIDI") != "1":
        pytest.skip("macOS CI only")
    pytest.fail("\n".join(RESULTS))
