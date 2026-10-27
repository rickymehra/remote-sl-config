"""MIDI transport behind a small interface so everything above it can run without hardware.

* :class:`FakeMidiPort` - in-memory, used by tests and by default in the TUI/CLI.
* :class:`MidoPort` - real ports via mido/python-rtmidi. Only built when the user passes
  ``--device``; ``mido`` is imported lazily so the rest of the tool never needs a MIDI backend.

Sending always goes through :func:`send_template`, which refuses to transmit unless a
confirmation callback approves the exact bytes.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from typing import Protocol, runtime_checkable

from .sysex import EOX, SOX, split_messages

# Shown before anything is sent to real hardware (CLI prompt, TUI dialog, capture wizard).
HARDWARE_WARNING = (
    "UNTESTED on real hardware: the template format is reverse-engineered and partly guessed. "
    "Sending can overwrite templates on your SL. Back up first (Global > Template Dump > All). "
    "Use at your own risk."
)


class MidiIOError(RuntimeError):
    pass


class SendCancelled(MidiIOError):
    pass


@runtime_checkable
class MidiPort(Protocol):
    name: str

    def send(self, message: bytes) -> None:
        """Send one complete SysEx message (F0 ... F7)."""

    def receive(self, timeout: float) -> bytes | None:
        """Return the next complete SysEx message, or None after ``timeout`` seconds."""

    def close(self) -> None: ...


class FakeMidiPort:
    """In-memory port. ``inbox`` feeds :meth:`receive`; :attr:`sent` records :meth:`send`."""

    def __init__(self, name: str = "Fake ReMOTE SL", inbox: Iterable[bytes] = ()) -> None:
        self.name = name
        self.inbox: deque[bytes] = deque(inbox)
        self.sent: list[bytes] = []
        self.closed = False
        self.echo = False  # when True, sent messages are queued back (loopback device)

    def send(self, message: bytes) -> None:
        if self.closed:
            raise MidiIOError("port closed")
        _check_sysex(message)
        self.sent.append(bytes(message))
        if self.echo:
            self.inbox.append(bytes(message))

    def receive(self, timeout: float) -> bytes | None:
        if self.closed:
            raise MidiIOError("port closed")
        return self.inbox.popleft() if self.inbox else None

    def close(self) -> None:
        self.closed = True


def resolve_port_name(name: str, available: list[str], kind: str = "MIDI") -> str:
    """Exact port name, else the one port whose name contains ``name`` (case-insensitive).

    OSes decorate names (Linux: "ReMOTE SL:ReMOTE SL MIDI 1 20:0"), so "ReMOTE SL Port 1" or
    just "Port 1" should be enough to pick the right one.
    """
    if name in available:
        return name
    hits = [n for n in available if name.lower() in n.lower()]
    if len(hits) == 1:
        return hits[0]
    listing = ", ".join(repr(n) for n in available) or "none"
    if not hits:
        raise MidiIOError(f"no {kind} port matching {name!r}; available: {listing}")
    raise MidiIOError(f"{name!r} matches several {kind} ports: {hits}; be more specific")


class SysexAssembler:
    """Rebuilds complete SysEx messages from MIDI input chunks of any size.

    The OS MIDI layer does not promise one chunk per message: a large SysEx can arrive
    split across chunks or joined with the next one. mido drops any chunk that is not
    exactly one message; on macOS CI that lost about a quarter of a 40-template dump.
    Here bytes are joined into a stream instead; realtime bytes are skipped, and a
    message cut short by another status byte is discarded.
    """

    def __init__(self) -> None:
        self._buf: bytearray | None = None

    def feed(self, chunk: bytes) -> list[bytes]:
        done: list[bytes] = []
        for b in chunk:
            if b >= 0xF8:  # realtime (clock, active sensing) may appear anywhere
                continue
            if b == SOX:
                self._buf = bytearray([SOX])
            elif self._buf is None:
                continue  # outside SysEx: channel messages are not ours
            elif b == EOX:
                self._buf.append(EOX)
                done.append(bytes(self._buf))
                self._buf = None
            elif b & 0x80:
                self._buf = None  # interrupted by another message
            else:
                self._buf.append(b)
        return done


class MidoPort:
    """Real MIDI port pair: mido for output, python-rtmidi directly for input (see
    :class:`SysexAssembler` for why). Use 'ReMOTE SL Port 1' for templates.

    Tested end to end against virtual ports on macOS CI (tests/test_midi_virtual.py); the
    behaviour of the SL itself is still untested.
    """

    def __init__(self, name: str) -> None:
        try:
            import mido
            import rtmidi
        except ImportError as e:  # pragma: no cover - depends on local install
            raise MidiIOError("mido/python-rtmidi is not installed") from e
        self._mido = mido
        self._assembler = SysexAssembler()
        self._inbox: queue.Queue[bytes] = queue.Queue()
        try:
            out_name = resolve_port_name(name, mido.get_output_names(), "output")
            self._in = rtmidi.MidiIn()
            in_names = self._in.get_ports()
            in_name = resolve_port_name(name, in_names, "input")
            self._out = mido.open_output(out_name)
            self._in.ignore_types(sysex=False, timing=True, active_sense=True)
            self._in.set_callback(self._on_chunk)
            self._in.open_port(in_names.index(in_name))
        except (OSError, ValueError, SystemError) as e:
            raise MidiIOError(f"cannot open MIDI port {name!r}: {e}") from e
        self.name = out_name

    def _on_chunk(self, event, _data=None) -> None:
        for msg in self._assembler.feed(bytes(event[0])):
            self._inbox.put(msg)

    def send(self, message: bytes) -> None:
        _check_sysex(message)
        self._out.send(self._mido.Message("sysex", data=list(message[1:-1])))

    def receive(self, timeout: float) -> bytes | None:
        try:
            return self._inbox.get(timeout=max(timeout, 0))
        except queue.Empty:
            return None

    def close(self) -> None:
        # detach the callback first: closing an input while CoreMIDI delivers to it can block
        self._in.cancel_callback()
        self._in.close_port()
        self._in.delete()
        self._out.close()


def list_ports() -> tuple[list[str], list[str]]:  # pragma: no cover - hardware only
    import mido

    return mido.get_input_names(), mido.get_output_names()


def open_port(device: str | None) -> MidiPort:
    """``None`` gives the fake port; a name opens real hardware."""
    return FakeMidiPort() if device is None else MidoPort(device)


def _check_sysex(message: bytes) -> None:
    if len(message) < 2 or message[0] != SOX or message[-1] != EOX:
        raise MidiIOError("refusing to send: not a single F0..F7 SysEx message")
    if any(b & 0x80 for b in message[1:-1]):
        raise MidiIOError("refusing to send: data byte with bit 7 set")


def describe(data: bytes) -> str:
    msgs = split_messages(data)
    return f"{len(msgs)} SysEx message(s), {len(data)} bytes"


def send_template(
    port: MidiPort,
    data: bytes,
    confirm: Callable[[str], bool],
    *,
    gap: float = 0.05,
    progress: Callable[[int, int], None] | None = None,
) -> int:
    """Send every message in ``data`` after ``confirm`` approves. Returns messages sent.

    ``confirm`` receives a human-readable summary and must return True; anything else
    raises :class:`SendCancelled` without sending a byte. ``progress(done, total)`` is
    called after each message.
    """
    msgs = split_messages(data)
    if not msgs:
        raise MidiIOError("nothing to send")
    summary = f"{HARDWARE_WARNING}\nSend {describe(data)} to {port.name!r}?"
    if confirm(summary) is not True:
        raise SendCancelled("send not confirmed")
    for i, msg in enumerate(msgs):
        port.send(msg.data)
        if progress:
            progress(i + 1, len(msgs))
        if gap and i + 1 < len(msgs) and not isinstance(port, FakeMidiPort):
            time.sleep(gap)  # pragma: no cover - give the SL time to store each template
    return len(msgs)


def receive_dump(
    port: MidiPort,
    *,
    timeout: float = 30.0,
    count: int = 1,
    cancel: threading.Event | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> list[bytes]:
    """Collect ``count`` SysEx messages (e.g. templates dumped from the device).

    Stops early when ``cancel`` is set (checked at least every 0.25 s), returning what
    arrived so far; safe to run in a worker thread. ``progress(received, count)`` is called
    after each message.
    """
    got: list[bytes] = []
    deadline = time.monotonic() + timeout
    while len(got) < count:
        if cancel is not None and cancel.is_set():
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        msg = port.receive(min(remaining, 0.25))
        if msg is None:
            if isinstance(port, FakeMidiPort):
                break
            continue
        got.append(msg)
        if progress:
            progress(len(got), count)
    return got
