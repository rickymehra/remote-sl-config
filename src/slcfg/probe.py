"""Send-and-observe probe for the channel (+19) and port (+18) codes (issue #1).

Each of records 0-55 (encoders, pots, sliders, the four button rows) becomes a CC control
whose CC number is its record index and whose byte under test holds a different candidate
code. The template goes to the SL's edit buffer; the owner moves every control while we log
what arrives on each USB port. CC number -> record -> code; the status byte gives the
channel and the input port gives U1/U2/U3. Codes that send nothing route to M1/M2 or OFF.

    uv run python -m slcfg.probe port --device "ReMOTE SL" --seconds 90
    uv run python -m slcfg.probe chan --fixed 0x01 --device "ReMOTE SL" --seconds 90
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path

from . import codec, midi_io
from .model import SLOT_BY_KEY

PROBED = range(56)  # encoders, pots, sliders, button rows 1-4
CODES = [
    *range(0x00, 0x10),
    *range(0x40, 0x50),
    *range(0x20, 0x30),
    0x10,
    0x30,
    0x50,
    0x60,
    0x70,
    0x7F,
]
assert len(CODES) <= len(PROBED) and len(set(CODES)) == len(CODES)
FIELD = {"port": "port", "chan": "channel"}
DEFAULT_FIXED = {"port": 0x00, "chan": 0x47}  # the other byte, held constant


def build(
    base: bytes, test: str, fixed: int | None = None, header: dict[int, int] | None = None
) -> tuple[bytes, dict[int, int]]:
    """Probe template from ``base`` (one 4112-byte template). Returns (sysex, {cc: code})."""
    t = codec.decode(base)
    t.name = f"PROBE {test.upper()}"
    other = "channel" if test == "port" else "port"
    fixed = DEFAULT_FIXED[test] if fixed is None else fixed
    plan: dict[int, int] = {}
    for c in t.controls.values():
        i = SLOT_BY_KEY[c.slot].index
        if i in PROBED and i - PROBED.start < len(CODES):
            code = CODES[i - PROBED.start]
            c.name, c.type, c.number = f"{test[0].upper()} {code:02X}", "cc", i
            setattr(c, FIELD[test], code)
            setattr(c, other, fixed)
            plan[i] = code
        else:
            c.type = "none"  # nothing else may send a CC that collides with a probe number
    msg = bytearray(codec.encode(t))
    msg[codec.BULK_FLAG_OFFSET] = 0  # single template: lands in the edit buffer
    for off, val in (header or {}).items():  # raw template-settings bytes, e.g. 102 = common port
        msg[off] = val
    return bytes(msg), plan


def analyse(events: list[tuple[str, list[int]]], plan: dict[int, int]) -> dict[int, dict]:
    """``events`` = (input port name, MIDI bytes). Returns {code: {ports, channels, count}}."""
    out = {code: {"ports": set(), "channels": set(), "count": 0} for code in plan.values()}
    for port, msg in events:
        if len(msg) == 3 and msg[0] & 0xF0 == 0xB0 and msg[1] in plan:
            row = out[plan[msg[1]]]
            row["ports"].add(port)
            row["channels"].add((msg[0] & 0x0F) + 1)
            row["count"] += 1
    return out


def report(test: str, result: dict[int, dict]) -> str:
    lines = [f"{test} code -> USB ports, channels (messages)"]
    for code, r in sorted(result.items()):
        seen = (
            f"{', '.join(sorted(r['ports']))}; ch {sorted(r['channels'])} ({r['count']})"
            if r["count"]
            else "nothing over USB"
        )
        lines.append(f"  {code:02X}  {seen}")
    return "\n".join(lines)


def listen(seconds: float) -> list[tuple[str, list[int]]]:  # pragma: no cover - hardware
    import rtmidi

    events: list[tuple[str, list[int]]] = []
    lock = threading.Lock()
    ins = []
    names = rtmidi.MidiIn().get_ports()
    for i, name in enumerate(names):
        if "ReMOTE SL" not in name:
            continue
        mi = rtmidi.MidiIn()
        mi.ignore_types(sysex=True, timing=True, active_sense=True)

        def cb(ev, _d=None, name=name):
            with lock:
                events.append((name, list(ev[0])))

        mi.set_callback(cb)
        mi.open_port(i)
        ins.append(mi)
    try:
        time.sleep(seconds)
    finally:
        for mi in ins:
            mi.cancel_callback()
            mi.close_port()
    return events


def main() -> None:  # pragma: no cover - hardware
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("test", choices=["port", "chan"])
    ap.add_argument("--device", default="ReMOTE SL Port 1")
    ap.add_argument(
        "--base", type=Path, default=Path("dumps/community/novation-factory-os41/36_-_-_User2.syx")
    )
    ap.add_argument("--fixed", type=lambda s: int(s, 0), help="value for the other byte")
    ap.add_argument(
        "--header", nargs="*", default=[], help="raw header bytes OFFSET=VALUE, e.g. 102=0x50"
    )
    ap.add_argument("--seconds", type=float, default=90)
    ap.add_argument("--out", type=Path, default=Path("dumps/captures"))
    a = ap.parse_args()
    header = {int(k, 0): int(v, 0) for k, v in (h.split("=") for h in a.header)}
    data, plan = build(a.base.read_bytes(), a.test, a.fixed, header)
    tag = a.test + ("_hdr" if header else "")
    (a.out / f"probe_{tag}.syx").write_bytes(data)
    port = midi_io.open_port(a.device)
    try:
        midi_io.send_template(port, data, lambda s: True)
    finally:
        port.close()
    print(
        f"sent PROBE {a.test.upper()}; move every encoder, pot, slider and button now "
        f"({a.seconds:.0f} s)",
        flush=True,
    )
    events = listen(a.seconds)
    (a.out / f"probe_{tag}.json").write_text(json.dumps({"plan": plan, "events": events}, indent=0))
    print(report(a.test, analyse(events, plan)))


if __name__ == "__main__":  # pragma: no cover
    main()
