"""A pretend ReMOTE SL for rehearsing ``slcfg capture --simulate`` without hardware.

Each capture step's dump is synthesised from the factory User2 template plus the changes the
step asks for, encoded the way FORMAT.md *currently guesses*. Its findings therefore confirm
our own hypotheses and prove nothing about the real unit; they only exercise the workflow.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from . import codec
from .capture import slot_to_code
from .model import SLOT_BY_KEY
from .sysex import split_messages

# Hypothesised codes (FORMAT.md H-chan / H-port and the C4-C7 guesses).
CHAN = {"1": 0x00, "2": 0x01, "16": 0x0F, "Keyb": 0x20, "Comn": 0x40}
PORT = {"OFF": 0x00, "U1": 0x01, "U2": 0x02, "U3": 0x03, "M1": 0x04, "M2": 0x08}


class SimulatedSL:
    """Implements :class:`slcfg.midi_io.MidiPort`; the wizard calls :meth:`prepare` per step."""

    name = "Simulated ReMOTE SL"

    def __init__(self, root: Path) -> None:
        factory = root / "dumps/community/novation-factory-os41"
        self.user2 = (factory / "36_-_-_User2.syx").read_bytes()
        self.bulk = (factory / "bulk/SL_Factory_Templates_OS41.syx").read_bytes()
        self.edit_buffer: bytes | None = None
        self.queue: deque[bytes] = deque()
        self.sent: list[bytes] = []

    # MidiPort ------------------------------------------------------------------------------
    def send(self, message: bytes) -> None:
        self.sent.append(bytes(message))
        self.edit_buffer = bytes(message)

    def receive(self, timeout: float) -> bytes | None:
        return self.queue.popleft() if self.queue else None

    def close(self) -> None:
        pass

    # simulation ------------------------------------------------------------------------------
    def prepare(self, step_id: str) -> None:
        self.queue.clear()
        if step_id == "C0":
            self.queue.extend(m.data for m in split_messages(self.bulk))
        elif step_id == "C11":
            self.queue.append(
                bytes([0xF0, 0x00, 0x20, 0x29, 0x02, 0x03, 0x7F, 0x02, *[0] * 120, 0xF7])
            )
        elif step_id == "C12":
            self.queue.append(self.edit_buffer or self.user2)
        else:
            self.queue.append(self.dump(step_id))

    def dump(self, step_id: str) -> bytes:
        t = codec.decode(self.user2)
        n = step_id[1:].rstrip("b")
        header: dict[int, int] = {}
        raw: dict[tuple[str, int], int] = {}

        def ctl(slot: str, **fields: object):
            c = t.control(slot)
            c.name = f"C{n} {slot_to_code(slot)}"
            for k, v in fields.items():
                setattr(c, k, v)
            return c

        if step_id == "C2":
            for i, ch in enumerate(["1", "2", "16", "Keyb", "Comn"]):
                ctl(f"encoder_{i + 1}", type="cc", channel=CHAN[ch])
            ctl("encoder_6", type="cc")
            ports = [0x00, 0x01, 0x02, 0x03, 0x04, 0x08, 0x20, 0x40]
            for i, p in enumerate(ports):
                ctl(f"pot_{i + 1}", type="cc", port=p)
            combos = [0x05, 0x06, 0x07, 0x09, 0x0C, 0x0D, 0x0F, 0x0A]
            for i, p in enumerate(combos):
                ctl(f"slider_{i + 1}", type="cc", port=p)
        elif step_id == "C3":
            header.update({97: 0, 99: 4, 100: 0x04, 101: 8, 102: 0x0A, 105: 1, 65: 3, 66: 2})
        elif step_id == "C4":
            for i, d in enumerate([1, 6, 7, 4, 5]):
                ctl(f"encoder_{i + 1}", type="cc", display=d)
            ctl("encoder_4", low=300, high=9000)
            ctl("encoder_6", type="cc", low=10, high=100)
            for i, code in enumerate([0x10, 0x11, 0x50, 0x51]):
                ctl(f"pot_{i + 1}", type="cc")
                raw[(f"pot_{i + 1}", 14)] = code
            ctl("slider_1", type="cc", low=127, high=0)
            ctl("slider_2", type="cc", value=63)
        elif step_id == "C5":
            for i, mode in enumerate(["normal", "momentary", "toggle", "step"]):
                ctl(f"button_row1_{i + 1}", type="cc", button_mode=mode)
            ctl("button_row1_4", step=5)
            ctl("button_row1_5", type="cc", display=3)
            ctl("button_row1_6", type="cc", display=8)
            ctl("button_row1_7", type="none", display=10)
            for i, typ in enumerate(
                [
                    "note",
                    "program_change",
                    "bank_change",
                    "realtime",
                    "template",
                    "mmc",
                    "nrpn",
                    "rpn",
                ]
            ):
                ctl(f"button_row2_{i + 1}", type=typ)
            ctl("button_row2_1", low=60, high=100, button_mode="momentary")
            ctl("button_row2_5", low=12)
            ctl("button_row2_6", low=3, high=5)
            ctl("button_row2_7", number_msb=3, number=4)
            ctl("button_row2_8", number_msb=0, number=5)
        elif step_id == "C6":
            for i, ms in enumerate([0, 10, 1000]):
                ctl(f"drum_pad_{i + 1}", type="drum_note", low=36, high=ms)
            ctl("drum_pad_4", type="drum_note", low=36)
            raw[("drum_pad_4", 14)] = 0x58
            ctl("drum_pad_5", type="cc", button_mode="momentary")
            ctl("drum_pad_6", type="cc", button_mode="toggle")
            for i, code in enumerate([0x11, 0x12, 0x13, 0x10]):
                key = ["touchpad_x1", "touchpad_y1", "touchpad_x2", "touchpad_y2"][i]
                ctl(key, type="cc")
                raw[(key, 14)] = code
            ctl("touchpad_y2", type="pitch_bend")
            ctl("sustain", button_mode="toggle")
            ctl("expression")
            raw[("expression", 14)] = 0x11
            ctl("pitch", type="cc", number=3)
        elif step_id == "C7":
            c = ctl("encoder_1", type="sysex")
            c.sysex.data_type, c.sysex.length, c.sysex.data_position = 1, 6, 4
            c.sysex.data = [0x7D, 0x01, 0x02, 0x7F, 0x03, 0x04]
            for i, dt in enumerate([2, 3, 4]):
                c = ctl(f"encoder_{i + 2}", type="sysex")
                c.sysex.data_type, c.sysex.length = dt, 10 if dt == 2 else 6
            c = ctl("encoder_5", type="sysex")
            c.sysex.data_type, c.sysex.length, c.sysex.data = 0, 3, [0x7D, 0x10, 0x11]
        elif step_id == "C8":
            header.update(
                {112 + 2: 36, 112 + 3: 59, 112 + 4: 69, 122 + 2: 60, 122 + 3: 84, 122 + 4: 52}
            )
        elif step_id == "C9":
            header.update({106: 3, 107: 17, 108: 1})

        data = bytearray(codec.encode(t))
        for off, v in header.items():
            data[off] = v
        for (slot, rel), v in raw.items():
            data[codec.RECORD_BASE + SLOT_BY_KEY[slot].index * codec.RECORD_LEN + rel] = v
        return bytes(data)
