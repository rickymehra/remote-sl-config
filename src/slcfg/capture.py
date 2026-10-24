"""Guided hardware capture session (``slcfg capture``), following docs/CAPTURE_PLAN.md.

The owner changes settings on the SL by hand; everything else is automated: instructions,
listening for the dump, saving ``dumps/captures/C<n>.syx`` with a sidecar note, an annotated
diff against the baseline, live checks of the FORMAT.md hypotheses, and FINDINGS.md.

Naming convention: every control touched in capture n is renamed ``C<n> <code>`` on the
SL (e.g. ``C2 E1`` for encoder 1). That lets every capture confirm the record order.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from . import codec, midi_io
from .model import SLOT_BY_INDEX, SLOT_BY_KEY, Template
from .sysex import split_messages, u14_be

# ---- control codes used in on-device names ("C2 E1") ----------------------------------------

_ROW_CODES = {
    "E": "encoder",
    "P": "pot",
    "S": "slider",
    "A": "button_row1",
    "B": "button_row2",
    "C": "button_row3",
    "D": "button_row4",
    "K": "drum_pad",
}
_SINGLE_CODES = {
    "X1": "touchpad_x1",
    "Y1": "touchpad_y1",
    "X2": "touchpad_x2",
    "Y2": "touchpad_y2",
    "JX": "pitch",
    "JY": "mod",
    "EX": "expression",
    "SU": "sustain",
    "RW": "rewind",
    "FF": "forward",
    "ST": "stop",
    "PL": "play",
    "RC": "record",
    "LP": "loop",
}


def code_to_slot(code: str) -> str | None:
    """``E1`` -> ``encoder_1``, ``SU`` -> ``sustain``; None if not a control code."""
    code = code.upper()
    if code in _SINGLE_CODES:
        return _SINGLE_CODES[code]
    m = re.fullmatch(r"([EPSABCDK])([1-8])", code)
    if m:
        return f"{_ROW_CODES[m.group(1)]}_{m.group(2)}"
    m = re.fullmatch(r"XT(\d{1,2})", code)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"extra_{int(m.group(1))}"
    return None


def slot_to_code(slot: str) -> str:
    for code, s in _SINGLE_CODES.items():
        if s == slot:
            return code
    group, _, n = slot.rpartition("_")
    if group == "extra":
        return f"XT{n}"
    for letter, g in _ROW_CODES.items():
        if g == group:
            return f"{letter}{n}"
    raise KeyError(slot)


# ---- findings and annotated changes ----------------------------------------------------------


@dataclass
class Finding:
    status: str  # "ok" (hypothesis confirmed), "new" (learned a value), "warn", "info"
    text: str

    def __str__(self) -> str:
        mark = {"ok": "✔", "new": "★", "warn": "⚠", "info": "·"}[self.status]
        return f"{mark} {self.text}"


@dataclass(frozen=True)
class Change:
    offset: int
    where: str  # control slot key, or "header"/"trailer"
    field: str  # field name from the offset table, or "+NN ?"
    old: int
    new: int


def _record_field_names() -> dict[int, str]:
    names: dict[int, str] = {}
    for f in codec.RECORD_FIELDS:
        for k in range(f.size):
            names[f.offset + k] = f.name if f.size == 1 else f"{f.name}[{k}]"
    return names


_REC_FIELD = _record_field_names()
_HDR_FIELD: dict[int, str] = {}
for _f in codec.HEADER_FIELDS:
    for _k in range(_f.size):
        _HDR_FIELD[_f.offset + _k] = _f.name
for _z in range(4):
    for _k in range(10):
        _HDR_FIELD.setdefault(112 + 10 * _z + _k, f"zone{_z + 1}+{_k}?")


def describe_changes(base: bytes, new: bytes) -> list[Change]:
    """Every differing byte of two template messages, located by control and field."""
    out = []
    for off, (a, b) in enumerate(zip(base, new, strict=False)):
        if a == b:
            continue
        if codec.RECORD_BASE <= off < codec.TRAILER_OFFSET:
            idx, rel = divmod(off - codec.RECORD_BASE, codec.RECORD_LEN)
            where = SLOT_BY_INDEX[idx].key
            name = _REC_FIELD.get(rel, f"+{rel:02d} ?")
            if not name.endswith("?"):
                name = f"+{rel:02d} {name}"
        elif off < codec.RECORD_BASE:
            where, name = "header", f"{off} {_HDR_FIELD.get(off, '?')}"
        else:
            where, name = "trailer", str(off)
        out.append(Change(off, where, name, a, b))
    return out


def format_changes(
    changes: list[Change], base: bytes | None = None, new: bytes | None = None
) -> str:
    """Changes grouped by control. With ``base``/``new`` given, a renamed control shows its
    whole old and new name on one line instead of one line per character."""
    if not changes:
        return "  (no differences)"
    lines = []
    last = None
    for c in changes:
        if c.where != last:
            code = ""
            if c.where in SLOT_BY_KEY:
                code = f" [{slot_to_code(c.where)}]"
            lines.append(f"  {c.where}{code}")
            last = c.where
            if base is not None and new is not None and c.where in SLOT_BY_KEY:
                off = codec.RECORD_BASE + SLOT_BY_KEY[c.where].index * codec.RECORD_LEN
                old_name, new_name = base[off : off + 8], new[off : off + 8]
                if old_name != new_name:
                    o = old_name.decode("latin-1").rstrip()
                    n = new_name.decode("latin-1").rstrip()
                    lines.append(f"      {'name':<24} {o!r} → {n!r}")
        if c.field.startswith("+0") and "name[" in c.field and base is not None:
            continue
        lines.append(f"      {c.field:<24} {c.old:02X} → {c.new:02X}   ({c.old:3d} → {c.new:3d})")
    return "\n".join(lines)


# ---- check context -----------------------------------------------------------------------------


@dataclass
class Ctx:
    step: Step
    base: bytes  # baseline template message (C1, or factory User2)
    msgs: list[bytes]  # what this capture received

    @property
    def new(self) -> bytes:
        return self.msgs[0]

    def rec(self, slot: str, data: bytes | None = None) -> bytes:
        data = self.new if data is None else data
        off = codec.RECORD_BASE + SLOT_BY_KEY[slot].index * codec.RECORD_LEN
        return data[off : off + codec.RECORD_LEN]

    def changed_slots(self) -> set[str]:
        return {c.where for c in describe_changes(self.base, self.new) if c.where in SLOT_BY_KEY}


Check = Callable[[Ctx], list[Finding]]


def _hexs(b: bytes) -> str:
    return b.hex(" ").upper()


def check_names(ctx: Ctx) -> list[Finding]:
    """Controls renamed 'C<n> <code>' must sit in the record the code predicts."""
    if not ctx.step.template_dump:
        return []
    t = codec.decode(ctx.new)
    ok, bad = [], []
    prefix = f"C{ctx.step.number}"
    for key, c in t.controls.items():
        parts = c.name.split()
        if len(parts) == 2 and parts[0].upper() == prefix:
            expected = code_to_slot(parts[1])
            if expected is None:
                continue  # not a control code, e.g. C12's "C12 OK" label
            (ok if expected == key else bad).append((c.name, key, expected))
    out = []
    if ok:
        out.append(Finding("ok", f"record order: {len(ok)} renamed control(s) sit where expected"))
    for name, key, expected in bad:
        out.append(Finding("warn", f"'{name}' found in {key}, expected {expected}: record order?"))
    if not ok and not bad and ctx.step.expects_names:
        out.append(Finding("warn", f"no control named '{prefix} …' found; were the names set?"))
    return out


# ---- per-step checks -----------------------------------------------------------------------


def check_c0(ctx: Ctx) -> list[Finding]:
    out = [Finding("info", f"received {len(ctx.msgs)} message(s)")]
    if len(ctx.msgs) != 40:
        out.append(Finding("warn", "expected 40 templates for an 'All' dump"))
    flags = {m[codec.BULK_FLAG_OFFSET] for m in ctx.msgs if len(m) == codec.MESSAGE_LEN}
    out.append(
        Finding("ok" if flags == {1} else "new", f"bulk flag (byte 7) values: {sorted(flags)}")
    )
    stamps = sorted({_hexs(m[9:11]) for m in ctx.msgs if len(m) == codec.MESSAGE_LEN})
    out.append(Finding("new", f"header bytes 9-10 on a live 'All' dump: {', '.join(stamps)}"))
    factory = ctx.step.reference("bulk")
    if factory:
        ref = [m.data for m in split_messages(factory.read_bytes())]
        changed = [
            codec.decode(m).name.split("  ")[0]
            for m, r in zip(ctx.msgs, ref, strict=False)
            if m[13:] != r[13:]
        ]
        out.append(Finding("info", f"{len(changed)} slot(s) differ from factory: {changed[:8]}"))
    return out


def check_c1(ctx: Ctx) -> list[Finding]:
    t = codec.decode(ctx.new)
    out = [
        Finding("info", f"template '{t.name.strip()}' in slot {t.slot}"),
        Finding("new", f"'Current' dump header bytes 7..12: {_hexs(ctx.new[7:13])}"),
    ]
    factory = ctx.step.reference("user2")
    if factory and t.slot == 36:
        diff = describe_changes(factory.read_bytes(), ctx.new)
        body = [c for c in diff if c.offset >= 13]
        out.append(
            Finding(
                "ok" if not body else "info",
                f"body vs factory User2: {len(body)} differing byte(s)"
                + (f" at {sorted({c.where for c in body})}" if body else ""),
            )
        )
        hdr = [c for c in diff if c.offset < 13]
        if hdr:
            out.append(
                Finding(
                    "new",
                    "header vs factory file: "
                    + ", ".join(f"byte {c.offset} {c.old:02X}→{c.new:02X}" for c in hdr),
                )
            )
    return out


def check_c1b(ctx: Ctx) -> list[Finding]:
    hdr = [c for c in describe_changes(ctx.base, ctx.new) if c.offset < codec.RECORD_BASE]
    if not hdr:
        return [Finding("ok", "numbered dump has the same header as 'Current'")]
    return [
        Finding(
            "new",
            "numbered vs Current dump: "
            + ", ".join(f"byte {c.offset} {c.old:02X}→{c.new:02X}" for c in hdr),
        )
    ]


def check_c2(ctx: Ctx) -> list[Finding]:
    out = []
    chans = ["1", "2", "16", "KeybCHAN", "ComnCHAN"]
    table = {label: ctx.rec(f"encoder_{i + 1}")[19] for i, label in enumerate(chans)}
    out.append(
        Finding(
            "new", "channel codes (+19): " + ", ".join(f"{k}={v:02X}" for k, v in table.items())
        )
    )
    h = table["1"] & 0x0F == 0 and table["2"] & 0x0F == 1 and table["16"] & 0x0F == 15
    out.append(
        Finding(
            "ok" if h else "warn",
            "H-chan: low nibble = channel − 1" + ("" if h else " does NOT hold"),
        )
    )
    ports = ["OFF", "U1", "U2", "U3", "M1", "M2", "KeybPORT", "ComnPORT"]
    pt = {label: ctx.rec(f"pot_{i + 1}")[18] for i, label in enumerate(ports)}
    out.append(
        Finding("new", "port codes (+18): " + ", ".join(f"{k}={v:02X}" for k, v in pt.items()))
    )
    hp = (
        (pt["U1"] & 3, pt["U2"] & 3, pt["U3"] & 3) == (1, 2, 3)
        and bool(pt["M1"] & 4)
        and bool(pt["M2"] & 8)
    )
    out.append(
        Finding(
            "ok" if hp else "warn",
            "H-port: bits0-1 USB port, bit2 M1, bit3 M2" + ("" if hp else " does NOT hold"),
        )
    )
    combos = ["U1 M1", "U2 M1", "U3 M1", "U1 M2", "M1 M2", "U1 M1 M2", "U3 M1 M2", "U2 M2"]
    out.append(
        Finding(
            "new",
            "port combos (+18): "
            + ", ".join(f"{k}={ctx.rec(f'slider_{i + 1}')[18]:02X}" for i, k in enumerate(combos)),
        )
    )
    fresh = ctx.rec("encoder_6")
    out.append(Finding("new", f"fresh CC record defaults (encoder 6): {_hexs(fresh[8:29])}"))
    return out


def check_c3(ctx: Ctx) -> list[Finding]:
    hdr = [c for c in describe_changes(ctx.base, ctx.new) if c.where == "header"]
    out = [
        Finding(
            "new",
            "header bytes changed: "
            + (", ".join(f"{c.offset}: {c.old:02X}→{c.new:02X}" for c in hdr) or "none"),
        )
    ]
    for label, values in (("KeybChan 5", (4, 5)), ("ComnChan 9", (8, 9))):
        hits = [c.offset for c in hdr if c.new in values]
        out.append(Finding("new" if hits else "warn", f"{label}: candidate byte(s) {hits}"))
    size, pos = ctx.new[codec.GROUP_SIZE_OFFSET], ctx.new[codec.GROUP_POSITION_OFFSET]
    ok = (size, pos) == (3, 2)
    out.append(Finding("ok" if ok else "warn", f"group size/position at 65/66 = {size}/{pos}"))
    return out


def check_c4(ctx: Ctx) -> list[Finding]:
    r = ctx.rec("encoder_4")
    low, high = r[9:11], r[11:13]
    if low == bytes([0x02, 0x2C]):
        order = Finding("ok", "14-bit byte order: MSB first (300 = 02 2C) — codec is right")
    elif low == bytes([0x2C, 0x02]):
        order = Finding("warn", "14-bit byte order: LSB FIRST (300 = 2C 02) — flip _u14 in codec")
    else:
        order = Finding("warn", f"LowVal 300 stored as {_hexs(low)}: unexpected")
    out = [order, Finding("info", f"HighVal 9000 stored as {_hexs(high)} (MSB-first = 46 28)")]
    disp = ["-64/+63", "REL1", "REL2", "0-16K", "APOT"]
    out.append(
        Finding(
            "new",
            "DispType codes (+15): "
            + ", ".join(f"{d}={ctx.rec(f'encoder_{i + 1}')[15]}" for i, d in enumerate(disp)),
        )
    )
    resp = ["JUMP", "PICK-UP", "TEMPLATE", "GLOBAL"]
    out.append(
        Finding(
            "new",
            "Response, +13/+14 per pot: "
            + ", ".join(
                f"{d}={ctx.rec(f'pot_{i + 1}')[13]:02X}/{ctx.rec(f'pot_{i + 1}')[14]:02X}"
                for i, d in enumerate(resp)
            ),
        )
    )
    s1 = codec.decode(ctx.new).controls["slider_1"]
    out.append(
        Finding(
            "ok" if (s1.low, s1.high) == (127, 0) else "warn",
            f"inverted slider decodes low/high = {s1.low}/{s1.high}",
        )
    )
    s2 = codec.decode(ctx.new).controls["slider_2"]
    out.append(Finding("info", f"stored value of slider 2 (+20/+21) = {s2.value}"))
    return out


def check_c5(ctx: Ctx) -> list[Finding]:
    out = []
    types = ["NOTE", "PROG CHG", "BANK CHG", "REALTIME", "TEMPLATE", "MMC", "NRPN", "RPN"]
    expected = [6, 7, 8, 9, 12, 5, 2, 3]
    codes = [ctx.rec(f"button_row2_{i + 1}")[8] for i in range(8)]
    for name, exp, got in zip(types, expected, codes, strict=True):
        out.append(
            Finding(
                "ok" if exp == got else "new",
                f"type {name}: code {got}" + ("" if exp == got else f" (guessed {exp})"),
            )
        )
    modes = ["NORMAL", "MOMENTRY", "TOGGLE", "STEP"]
    m13 = [ctx.rec(f"button_row1_{i + 1}")[13] & 0x1C for i in range(4)]
    out.append(
        Finding(
            "ok" if m13 == [0, 4, 8, 16] else "warn",
            "button types (+13 bits 2-4): "
            + ", ".join(f"{m}={v}" for m, v in zip(modes, m13, strict=True)),
        )
    )
    step = ctx.rec("button_row1_4")[22]
    out.append(Finding("ok" if step == 5 else "warn", f"StepVal 5 at +22: {step}"))
    out.append(
        Finding(
            "new",
            f"ON/OFF, LED display codes (+15): "
            f"{ctx.rec('button_row1_5')[15]}, {ctx.rec('button_row1_6')[15]}",
        )
    )
    tpl = ctx.rec("button_row2_5")
    out.append(
        Finding(
            "new",
            f"TEMPLATE 12 stored as low={u14_be(tpl[9], tpl[10])} (12 → 1-based, 11 → 0-based)",
        )
    )
    nr = ctx.rec("button_row2_7")
    out.append(
        Finding(
            "ok" if (nr[16], nr[17]) == (3, 4) else "warn",
            f"NRPN msb/lsb at +16/+17 = {nr[16]}/{nr[17]}",
        )
    )
    for i, what in ((0, "NOTE C3 vel 100"), (2, "BANK msb 7 lsb 3"), (3, "REALTIME start/stop")):
        r = ctx.rec(f"button_row2_{i + 1}")
        out.append(Finding("new", f"{what}: bytes +9..+28 = {_hexs(r[9:29])}"))
    return out


def check_c6(ctx: Ctx) -> list[Finding]:
    out = []
    recs = {k: ctx.rec(f"drum_pad_{k}") for k in (1, 2, 3, 4)}
    for k, ms in ((2, 10), (3, 1000)):
        r = recs[k]
        hits = [o for o in range(9, 40) if u14_be(r[o], r[o + 1]) == ms]
        hits_le = [o for o in range(9, 40) if u14_be(r[o + 1], r[o]) == ms]
        txt = f"Auto-Off {ms} ms: MSB-first at {hits}, LSB-first at {hits_le}"
        out.append(Finding("new" if hits or hits_le else "warn", txt))
    diff = [o for o in range(41) if recs[4][o] != recs[1][o] and o >= 8]
    out.append(Finding("new", f"Off Sync (pad 4 vs pad 1) differs at offsets {diff}"))
    tm = ["HomeLeft", "HomeUp", "HomeCntr", "HOLD"]
    keys = ["touchpad_x1", "touchpad_y1", "touchpad_x2", "touchpad_y2"]
    out.append(
        Finding(
            "new",
            "TchMode +13/+14: "
            + ", ".join(
                f"{m}={ctx.rec(k)[13]:02X}/{ctx.rec(k)[14]:02X}"
                for m, k in zip(tm, keys, strict=True)
            ),
        )
    )
    out.append(
        Finding(
            "new",
            f"pad VELOCITY / TOGGLE +13: {ctx.rec('drum_pad_5')[13]:02X} / "
            f"{ctx.rec('drum_pad_6')[13]:02X}",
        )
    )
    jx = ctx.rec("pitch")
    out.append(
        Finding(
            "ok" if (jx[8], jx[17]) == (1, 3) else "warn",
            f"joystick X as CC 3: type {jx[8]}, number {jx[17]}",
        )
    )
    return out


def check_c7(ctx: Ctx) -> list[Finding]:
    out = []
    e1 = ctx.rec("encoder_1")
    body = e1[29 : 29 + 6]
    out.append(
        Finding(
            "ok" if (e1[26], e1[27], e1[28]) == (1, 6, 4) else "warn",
            f"SINGLE len 6 pos 4 → +26..+28 = {e1[26]} {e1[27]} {e1[28]}",
        )
    )
    out.append(Finding("new", f"sysex bytes stored as {_hexs(body)} (DV placeholder at 4th)"))
    names = ["ROLAND", "LSB-MSB", "MSB-LSB", "NONE"]
    out.append(
        Finding(
            "new",
            "DataType codes (+26): "
            + ", ".join(f"{n}={ctx.rec(f'encoder_{i + 2}')[26]}" for i, n in enumerate(names)),
        )
    )
    out.append(Finding("new", f"ROLAND record body: {_hexs(ctx.rec('encoder_2')[26:41])}"))
    return out


def check_header_values(*wanted: tuple[str, tuple[int, ...]]) -> Check:
    def check(ctx: Ctx) -> list[Finding]:
        hdr = [c for c in describe_changes(ctx.base, ctx.new) if c.where == "header"]
        out = [
            Finding(
                "new",
                "header bytes changed: "
                + (", ".join(f"{c.offset}: {c.old:02X}→{c.new:02X}" for c in hdr) or "none"),
            )
        ]
        for label, values in wanted:
            hits = [c.offset for c in hdr if c.new in values]
            out.append(Finding("new" if hits else "warn", f"{label}: candidate byte(s) {hits}"))
        return out

    return check


def check_c10(ctx: Ctx) -> list[Finding]:
    ex = sorted(s for s in ctx.changed_slots() if s.startswith("extra_"))
    if ex:
        return [Finding("new", f"editable extra records: {ex}")]
    return [Finding("info", "no extra record changed (Automap-only or unused)")]


def check_c11(ctx: Ctx) -> list[Finding]:
    return [
        Finding("new", f"globals dump: {len(m)} bytes, header {_hexs(m[:12])}") for m in ctx.msgs
    ]


def check_c12(ctx: Ctx) -> list[Finding]:
    sent = ctx.step.sent
    if sent is None:
        return [Finding("warn", "nothing was sent in this step")]
    body = [c for c in describe_changes(sent, ctx.new) if c.offset >= codec.TEMPLATE_NAME_OFFSET]
    hdr = [c for c in describe_changes(sent, ctx.new) if c.offset < codec.TEMPLATE_NAME_OFFSET]
    out = [
        Finding(
            "ok" if not body else "warn",
            "device kept our template byte for byte"
            if not body
            else f"{len(body)} byte(s) differ after the round trip:\n"
            + format_changes(body, sent, ctx.new),
        )
    ]
    if hdr:
        out.append(
            Finding(
                "new",
                "header after round trip: "
                + ", ".join(f"byte {c.offset} {c.old:02X}→{c.new:02X}" for c in hdr),
            )
        )
    if not body:
        out.append(Finding("ok", "no checksum needed: the SL accepted an encoder-written template"))
    return out


# ---- steps -------------------------------------------------------------------------------------

DUMP_CURRENT = "GLOBAL → page 4 → encoder 1 = Current → press button 1"
DUMP_ALL = "GLOBAL → page 4 → press button 2 (All)"


@dataclass
class Step:
    id: str  # "C0".."C12", "C1b"
    title: str
    instructions: list[str]
    dump: str = DUMP_CURRENT
    count: int = 1
    template_dump: bool = True
    expects_names: bool = True
    checks: list[Check] = field(default_factory=list)
    sends: bool = False
    issues: list[int] = field(default_factory=list)
    refs: dict[str, Path] = field(default_factory=dict)
    sent: bytes | None = None  # filled in by the wizard for C12

    @property
    def number(self) -> str:
        return self.id[1:].rstrip("b")

    def reference(self, key: str) -> Path | None:
        p = self.refs.get(key)
        return p if p and p.exists() else None


def _table(rows: list[tuple[str, str]]) -> list[str]:
    w = max(len(a) for a, _ in rows)
    return [f"  {a:<{w}}  {b}" for a, b in rows]


def build_steps(root: Path) -> list[Step]:
    factory = root / "dumps/community/novation-factory-os41"
    refs = {
        "bulk": factory / "bulk/SL_Factory_Templates_OS41.syx",
        "user2": factory / "36_-_-_User2.syx",
    }
    name_hint = (
        "Rename every control you touch to 'C{n} <code>' (E1 = encoder 1, P = pot, S = slider,"
        " A/B/C/D = button rows 1-4, K = pad)."
    )
    return [
        Step(
            "C0",
            "Full backup (do this first)",
            ["Nothing to change. This saves all 40 templates before anything else."],
            dump=DUMP_ALL,
            count=40,
            template_dump=True,
            expects_names=False,
            checks=[check_c0],
            issues=[8],
            refs=refs,
        ),
        Step(
            "C1",
            "Baseline",
            ["Select template 36 (User2). Touch nothing."],
            expects_names=False,
            checks=[check_c1],
            issues=[8],
            refs=refs,
        ),
        Step(
            "C1b",
            "Baseline, numbered dump",
            [
                "Still on template 36, touch nothing.",
                "This time dump by NUMBER: GLOBAL → page 4 → encoder 1 = 36 → button 1.",
            ],
            dump="GLOBAL → page 4 → encoder 1 = 36 → press button 1",
            expects_names=False,
            checks=[check_c1b],
            issues=[8],
        ),
        Step(
            "C2",
            "Channel and port codes",
            [
                name_hint.format(n=2),
                "Set every touched control to Control = CC first.",
                *_table(
                    [
                        ("Encoder 1..5", "MidiChan = 1, 2, 16, KeybCHAN, ComnCHAN"),
                        ("Encoder 6", "only Control = CC"),
                        ("Pot 1..8", "Ports = OFF, U1, U2, U3, M1, M2, KeybPORT, ComnPORT"),
                        (
                            "Slider 1..8",
                            "Ports = U1 M1, U2 M1, U3 M1, U1 M2, M1 M2, U1 M1 M2, U3 M1 M2, U2 M2",
                        ),
                    ]
                ),
            ],
            checks=[check_c2],
            issues=[1, 9],
        ),
        Step(
            "C3",
            "Template menu",
            [
                "Select template 36 again to discard earlier edits.",
                "TEMPLATE menu page 1: VelCurve SOFT 1, AfterTch OFF, KeybChan 5, KeybPort M1,",
                "  ComnChan 9, ComnPort U2 M2, PotMode PICK-UP.",
                "Page 2: Position 2, Size 3.",
            ],
            expects_names=False,
            checks=[check_c3],
            issues=[10],
        ),
        Step(
            "C4",
            "Ranges, display types, response, byte order",
            [
                name_hint.format(n=4),
                *_table(
                    [
                        ("Encoder 1..5", "CC; DispType = -64/+63, REL1, REL2, 0-16K, APOT"),
                        ("Encoder 4", "also LowVal 300, HighVal 9000"),
                        ("Encoder 6", "CC, LowVal 10, HighVal 100"),
                        ("Pot 1..4", "CC; Response = JUMP, PICK-UP, TEMPLATE, GLOBAL"),
                        ("Slider 1", "CC, LowVal 127, HighVal 0"),
                        ("Slider 2", "CC; move it to about the middle before dumping"),
                    ]
                ),
            ],
            checks=[check_c4],
            issues=[2, 3],
        ),
        Step(
            "C5",
            "Buttons and every message type",
            [
                name_hint.format(n=5),
                *_table(
                    [
                        (
                            "Btn row 1, 1..4",
                            "CC; BtnType NORMAL, MOMENTRY, TOGGLE, STEP (StepVal 5)",
                        ),
                        ("Btn row 1, 5..6", "CC; DispType ON/OFF, LED"),
                        ("Btn row 1, 7", "NoContrl, DispType LABEL"),
                        ("Btn row 2, 1", "NOTE C3, velocity 100, MOMENTRY"),
                        ("Btn row 2, 2", "PROG CHG LowProg 5, HighProg 10, STEP"),
                        ("Btn row 2, 3", "BANK CHG MSB-LSB, lsb 3, msb 7"),
                        ("Btn row 2, 4", "REALTIME RT-Start / RT-Stop, TOGGLE"),
                        ("Btn row 2, 5", "TEMPLATE 12"),
                        ("Btn row 2, 6", "MMC DEF PLAY, DeviceID 5"),
                        ("Btn row 2, 7", "NRPN msb 3, lsb 4"),
                        ("Btn row 2, 8", "RPN msb 0, lsb 5"),
                    ]
                ),
            ],
            checks=[check_c5],
            issues=[3, 4, 9],
        ),
        Step(
            "C6",
            "Pads, touchpad, pedals, joystick",
            [
                name_hint.format(n=6)
                + " Touchpad X1/Y1/X2/Y2, joystick JX, sustain SU, expression EX.",
                *_table(
                    [
                        ("Pad 1..3", "DRUMNOTE note 36; Auto-Off NONE, 10 ms, 1000 ms"),
                        ("Pad 4", "DRUMNOTE, Off Sync = 1/4 note"),
                        ("Pad 5..6", "CC; BtnType VELOCITY, TOGGLE"),
                        ("Touchpad X1,Y1,X2,Y2", "TchMode HomeLeft, HomeUp, HomeCntr, HOLD"),
                        ("Touchpad Y2", "also Control = PITCHBND"),
                        ("Sustain", "BtnType TOGGLE"),
                        ("Expression", "Response PICK-UP"),
                        ("Joystick X", "Control = CC 3"),
                    ]
                ),
            ],
            checks=[check_c6],
            issues=[5],
        ),
        Step(
            "C7",
            "SysEx block",
            [
                name_hint.format(n=7),
                *_table(
                    [
                        (
                            "Encoder 1",
                            "SYSEX, SINGLE, Length 6, DataPsn 4, bytes 7D 01 02 DV 03 04",
                        ),
                        ("Encoder 2", "SYSEX, ROLAND, Length 10"),
                        ("Encoder 3", "SYSEX, DispType 0-16K, LSB-MSB, Length 6, DataPsn 2"),
                        ("Encoder 4", "same as 3 but MSB-LSB"),
                        ("Encoder 5", "SYSEX, NONE, Length 3, bytes 7D 10 11"),
                    ]
                ),
            ],
            checks=[check_c7],
            issues=[6],
        ),
        Step(
            "C8",
            "Keyboard zones",
            [
                "Select template 36 again. TEMPLATE (press twice) → Keyboard Zones: Zones = ON.",
                "Zone 1: Low C1, High B2, Transpose +5, VelCurve HARD 1, MidiChan 3, Ports M2.",
                "Zone 2: Low C3, High C5, Transpose -12, MidiChan 4, Ports U1 M1.",
                "Page 2, zone 2: AfterTch OFF, PitchBnd ON, ModWheel OFF;",
                "  PitchBnd & ModWheel = USE ZONE CHAN PORTS.",
            ],
            expects_names=False,
            checks=[
                check_header_values(
                    ("Transpose +5 (69)", (69,)),
                    ("Transpose -12 (52)", (52,)),
                    ("C1 (36/24)", (36, 24)),
                    ("B2 (59/47)", (59, 47)),
                    ("C5 (84/72)", (84, 72)),
                )
            ],
            issues=[10],
        ),
        Step(
            "C9",
            "State saved with the template",
            [
                "Select template 36 again. Select POTS on the left and SLIDERS on the right.",
                "Press OCTAVE ▲ once. With DATA/SELECT send bank 3, then program 17.",
            ],
            expects_names=False,
            checks=[
                check_header_values(
                    ("bank 3", (3,)), ("program 17 (17/16)", (17, 16)), ("octave +1", (1, 65))
                )
            ],
            issues=[10],
        ),
        Step(
            "C10",
            "Extra records 78-89",
            [
                "Hold EDIT and press each ROW-SELECT, SCROLL, TAP TEMPO and OCTAVE button.",
                "If one opens an edit page: set CC 100+n and name it 'C10 XT<n>' (n = 1, 2, …).",
            ],
            expects_names=False,
            checks=[check_c10],
            issues=[7],
        ),
        Step(
            "C11",
            "Global settings",
            ["Nothing to change. This dumps the global settings (a different message)."],
            dump="GLOBAL → page 4 → press button 3 (Send Globals)",
            template_dump=False,
            expects_names=False,
            checks=[check_c11],
            issues=[8],
        ),
        Step(
            "C12",
            "Write path (sends to the SL)",
            [
                "Memory Protect must be OFF (GLOBAL menu).",
                "The wizard sends C1 with encoder 1 renamed 'C12 OK' on CC 74.",
                "After sending, check the left LCD shows C12 OK. Do not press WRITE.",
            ],
            sends=True,
            expects_names=False,
            checks=[check_c12],
            issues=[8],
        ),
    ]


# ---- session state ---------------------------------------------------------------------------


class Session:
    """Progress and findings in dumps/captures/session.json, so a session can resume."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.path = folder / "session.json"
        self.data: dict = {"steps": {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())

    def done(self, step_id: str) -> bool:
        return step_id in self.data["steps"]

    def record(self, step: Step, files: list[str], findings: list[Finding], notes: str) -> None:
        self.data["steps"][step.id] = {
            "title": step.title,
            "files": files,
            "when": datetime.now(UTC).isoformat(timespec="seconds"),
            "notes": notes,
            "findings": [{"status": f.status, "text": f.text} for f in findings],
        }
        self.save()

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2) + "\n")


def write_findings(session: Session, steps: list[Step], simulated: bool) -> Path:
    lines = ["# Capture findings", ""]
    if simulated:
        lines += [
            "> **SIMULATED rehearsal**: these results come from a fake SL built from the",
            "> FORMAT.md hypotheses, not from hardware.",
            "",
        ]
    for step in steps:
        entry = session.data["steps"].get(step.id)
        if not entry:
            lines.append(f"## {step.id} {step.title}: not captured")
            lines.append("")
            continue
        issues = ", ".join(f"#{n}" for n in step.issues)
        lines.append(f"## {step.id} {step.title} ({issues})")
        lines.append(f"Files: {', '.join(entry['files'])}  ·  {entry['when']}")
        if entry["notes"]:
            lines.append(f"Notes: {entry['notes']}")
        lines.append("")
        lines += [f"- {Finding(f['status'], f['text'])}" for f in entry["findings"]]
        lines.append("")
    out = session.folder / "FINDINGS.md"
    out.write_text("\n".join(lines))
    return out


# ---- the wizard ------------------------------------------------------------------------------


class UI(Protocol):
    def say(self, text: str = "") -> None: ...

    def ask(self, prompt: str, default: str = "") -> str: ...

    def confirm(self, prompt: str) -> bool: ...


@dataclass
class Wizard:
    port: midi_io.MidiPort
    ui: UI
    folder: Path
    root: Path
    timeout: float = 120.0
    simulated: bool = False
    steps: list[Step] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.steps = self.steps or build_steps(self.root)
        self.session = Session(self.folder)

    def baseline(self) -> bytes:
        c1 = self.folder / "C1.syx"
        if c1.exists():
            return c1.read_bytes()
        user2 = self.root / "dumps/community/novation-factory-os41/36_-_-_User2.syx"
        return user2.read_bytes()

    def run(self, only: str | None = None, redo: bool = False) -> None:
        ui = self.ui
        if self.simulated:
            ui.say("SIMULATED SL: rehearsal only, results are not real findings.")
        else:
            ui.say(f"⚠ {midi_io.HARDWARE_WARNING}")
        for step in self.steps:
            if only and step.id.lower() != only.lower():
                continue
            if self.session.done(step.id) and not (redo or only):
                continue
            if not self.do_step(step):
                break
        path = write_findings(self.session, self.steps, self.simulated)
        left = [s.id for s in self.steps if not self.session.done(s.id)]
        ui.say(f"\nFindings written to {path}.")
        ui.say("All steps captured." if not left else f"Still to do: {', '.join(left)}")

    def do_step(self, step: Step) -> bool:
        ui = self.ui
        ui.say(f"\n━━ {step.id}: {step.title} ━━")
        for line in step.instructions:
            ui.say(line)
        answer = ui.ask("Enter when ready, s = skip, q = quit", "").strip().lower()
        if answer == "q":
            return False
        if answer == "s":
            ui.say(f"skipped {step.id}")
            return True
        if step.sends and not self.send_test(step):
            return True
        while True:
            prepare = getattr(self.port, "prepare", None)
            if prepare:  # simulated SL: synthesise this step's dump
                prepare(step.id)
            ui.say(f"Listening… now on the SL: {step.dump}")
            msgs = midi_io.receive_dump(
                self.port,
                timeout=self.timeout,
                count=step.count,
                progress=getattr(ui, "progress", None) if step.count > 1 else None,
            )
            problem = self.validate(step, msgs)
            if not problem:
                break
            ui.say(f"⚠ {problem}")
            if ui.ask("r = retry, s = skip", "r").strip().lower() == "s":
                return True
        files = self.save(step, msgs)
        ctx = Ctx(step, self.baseline(), msgs)
        findings: list[Finding] = []
        if step.template_dump and step.count == 1 and step.id not in ("C1", "C12"):
            ui.say("Changes vs baseline:")
            ui.say(format_changes(describe_changes(ctx.base, ctx.new), ctx.base, ctx.new))
        for check in [check_names, *step.checks]:
            findings += check(ctx)
        for f in findings:
            ui.say(str(f))
        notes = ui.ask("Notes for this capture (optional)", "")
        self.write_sidecar(step, files, findings, notes)
        self.session.record(step, files, findings, notes)
        return True

    def validate(self, step: Step, msgs: list[bytes]) -> str | None:
        if not msgs:
            return "nothing received (check Global p4 Ports = U1 and the MIDI port)"
        if len(msgs) < step.count:
            return f"received {len(msgs)} of {step.count} messages"
        if step.template_dump:
            for m in msgs:
                try:
                    codec.decode(m)
                except codec.CodecError as e:
                    return f"not a template dump: {e}"
        return None

    def save(self, step: Step, msgs: list[bytes]) -> list[str]:
        self.folder.mkdir(parents=True, exist_ok=True)
        name = "C0_all.syx" if step.id == "C0" else f"{step.id}.syx"
        (self.folder / name).write_bytes(b"".join(msgs))
        return [name]

    def write_sidecar(
        self, step: Step, files: list[str], findings: list[Finding], notes: str
    ) -> None:
        body = [f"# {files[0]}: {step.id} {step.title}", ""]
        if self.simulated:
            body += ["**SIMULATED** (rehearsal, not from hardware)", ""]
        body += ["Settings changed on the SL:", "", *[f"    {line}" for line in step.instructions]]
        body += ["", f"Dumped with: {step.dump}", ""]
        if notes:
            body += [f"Notes: {notes}", ""]
        body += ["Findings:", "", *[f"- {f}" for f in findings], ""]
        (self.folder / f"{files[0]}.md").write_text("\n".join(body))

    def send_test(self, step: Step) -> bool:
        base = self.folder / "C1.syx"
        if not base.exists():
            self.ui.say("⚠ C12 needs C1.syx first")
            return False
        t: Template = codec.decode(base.read_bytes())
        c = t.controls["encoder_1"]
        c.name, c.type, c.number = "C12 OK", "cc", 74
        data = codec.encode(t)
        try:
            midi_io.send_template(self.port, data, lambda s: self.ui.confirm(s))
        except midi_io.SendCancelled:
            self.ui.say("send cancelled; skipping C12")
            return False
        step.sent = data
        (self.folder / "C12_sent.syx").write_bytes(data)
        self.ui.ask("Check the left LCD shows 'C12 OK', then press Enter", "")
        return True
