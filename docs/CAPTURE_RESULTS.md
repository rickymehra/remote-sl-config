# Capture results: hardware session 1 (2026-10-27)

First run against a real ReMOTE SL (issue #11). Captured C0, C1, C1b; stopped at C2 (see
"Next session"). Later in the session, with the owner's OK, tested the write path (C12) and
loaded the factory OS 4.1 set into all 40 slots (Memory Protect OFF).

Setup: ReMOTE SL over USB on macOS, ports `ReMOTE SL Port 1/2/3` (in and out) as documented.
**SL OS 4.2.02**, not the 4.1 the plan assumes.

## Files (`dumps/captures/`)

| File | What |
|---|---|
| `backup_all.syx` | Full backup, all 40 slots (`receive --count 40`). Keep it. |
| `C0_all.syx` | Wizard C0, a second Dump All. Byte-identical to `backup_all.syx`. |
| `C1.syx` | Template 35 (User1), dumped as **Current** (edit buffer), untouched. |
| `C1b.syx` | Template 35 dumped **by number**. |
| `C12_sent.syx`, `C12.syx` | C1 with encoder 1 renamed `C12 OK` (CC 74), sent; then dumped as Current. |
| `C12_readback.syx` | Current dump after sending unchanged `C1.syx` (inconclusive, see C12). |
| `after_factory_all.syx` | Dump All after sending the factory OS 4.1 bulk file. |
| `probe_13b.syx` | Two unsolicited 13-byte messages sent on template change (below). |
| `FINDINGS.md`, `session.json`, `*.md` | Wizard output; `slcfg capture` resumes at C2. |

Decode/encode round-trip of `backup_all.syx` is byte-identical, so the codec is lossless on
OS 4.2 data too.

## Findings

**#8 header bytes**
- Byte 7: `01` on bulk ("All") members, `00` on single dumps, both Current and numbered. ✔
- Bytes 9–10: `22 02` on every dump type (All, Current, numbered).
- Byte 12 = slot index, 0-based (`22` = slot 35), also for a Current dump.
- Dumps are deterministic: two Dump Alls a few minutes apart are byte-identical.
- A numbered dump equals the stored template (C1b vs slot 35 of C0: only byte 7 differs).

**#3 flags +14, and the stored value +21** (C1 Current vs C1b numbered, same template)
- The edit buffer is not byte-identical to the stored template:
  - E1, S1, S2 (r00, r16, r17) field +14: `10` in Current, `00` stored. The factory User1 file
    has `10`, so this bit may be runtime state that changes when the template is stored or used.
  - Pads K1–K3 (r56–r58) field +21: `00` in Current, `7F 4E 5D` stored. +21 holds a live value
    that is saved with the template and not loaded into the edit buffer.
- Seen on the SL's display, not dumped: a control switched from NoContrl to CC defaults to
  **Ports = ComnPORT, MidiChan = ComnCHAN** (relevant to #1).

**New: unsolicited SysEx on template change** (not in FORMAT.md)
```
select 34:  F0 00 20 29 03 03 10 05 05 00 01 01 F7
select 35:  F0 00 20 29 03 03 10 05 05 00 01 00 F7
```
Product byte `03` (templates use `02`). Only the last data byte differs. 34 is an Automap
template and 35 is not, so it may be an Automap on/off flag (guess; untested between two
non-Automap templates).

**C12 write path: works**
- Sending a single template (byte 7 = `00`) lands in the **edit buffer**: the SL showed
  `C12 OK` on encoder 1, and the Current dump matched what was sent apart from 3 bytes caused
  by touching controls: r00 +14 `10`→`00` and r00 +21 `2C`→`71` (encoder 1 turned: +21 is
  its live value, and touching it cleared bit `0x10` of +14, perhaps a "not moved since load"
  flag, #3), and r01 +15 `00`→`04` (encoder 2 DispType; unexplained, maybe a knob nudged in
  edit mode).
- Sending unchanged `C1.syx` and reading it back proved nothing on its own: the edit buffer
  already held those bytes. A test send needs a visible change.

**Bulk load: works, no checksum** (#8)
- The factory bulk file (40 messages, byte 7 = `01`), sent with a 0.5 s gap and Memory
  Protect OFF, was **stored straight into slots 1–40**, without pressing WRITE.
- Dump All afterwards matches the factory file byte for byte except **bytes 9–10**: file
  `21 07`, device `22 02`. Every dump from this OS 4.2.02 unit carries `22 02`, and factory
  files carry `21 07` / `21 09`, so **bytes 9–10 are the OS version of the unit that made the
  dump** and the SL rewrites them on dump. The SL accepted a template with a different value
  there, which also rules them out as a checksum.
- The owner's previous 40 templates are in `backup_all.syx`; restoring them is the same
  proven bulk send.

## Where the docs and the device disagreed

- **OS 4.2.02** instead of 4.1. Nothing in the format differed so far.
- **Slot 36 is not the empty User2** on a used SL (here it holds `JV-1010`). Used slot 35
  (User1) instead. The plan should not assume 36 is empty.
- **Dump All takes ~135 s** (about 3.3 s per template), longer than the wizard's default
  `--timeout 120`. Ran the wizard with `--timeout 300`.
- **The MIDI input buffers between steps.** A dump started while the wizard sat at a prompt
  was received in full on retry, and the 13-byte template-change message ended up as the
  first message of C1, which the wizard rejected (`expected 4112-byte template message, got 13`).
  The wizard could drain the input before each step, or skip non-template SysEx.
- Naming controls on the SL is slow, and entering digits was not obvious. For a full C2 that
  is the biggest cost.

## Next session: probe instead of hand edits

Setting every control by hand (C2 alone is 19 controls) is too slow. Plan: generate probe
templates on the computer, one candidate value per control in the byte under test, send them
to the **edit buffer** (never WRITE; needs explicit OK each time, which also covers C12), then
move every control and log what the SL sends on Port 1/2/3. The MIDI output gives channel,
USB port, value range, message type, button behaviour and pad Auto-Off timing per control,
which covers most of #1, #2, #4, #5, #6 and the zones in #10. Display-only fields (DispType,
names) and the DIN ports M1/M2 still need a look at the display.
