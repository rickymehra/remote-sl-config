# Capture plan (hardware session)

Goal: turn every **guess** in `docs/FORMAT.md` into **confirmed** with as few dumps as
possible. About 90 minutes, **13 captures**. Tracked in issue #11 ("Hardware session"),
with one issue per open question (#1–#10).

## The easy way: the capture wizard

```sh
uv run slcfg capture --device "ReMOTE SL Port 1"
```

It walks through every step below in order. For each step it shows what to change, listens
for the dump, saves `dumps/captures/C<n>.syx` with a sidecar note, prints the changes by
control and field, and checks the FORMAT.md guesses on the spot (✔ confirmed, ★ new value,
⚠ contradiction). Step C12 sends a template to the SL; you confirm before anything is sent.
At the end it writes `dumps/captures/FINDINGS.md` for the next session.

- Stop any time with `q`; run the same command again to resume.
- `--step C4` redoes a single step; `--redo` goes through all of them again.
- **Name every control you touch `C<n> <code>`** on the SL, e.g. `C2 E1`. The codes are E = encoder,
  P = pot, S = slider, A/B/C/D = button rows 1–4, K = drum pad, X1 Y1 X2 Y2 = touchpad,
  JX JY = joystick, SU = sustain, EX = expression. The wizard uses the names to confirm the
  record order.
- Rehearse now, without the keyboard: `uv run slcfg capture --simulate` (writes to
  `dumps/captures-sim/`, ignored by git; its results only echo our own guesses).

The manual commands below still work if you prefer them.

## Why so few captures

Each control has its own 41-byte record, so a change to encoder 1 can never land in encoder
2's bytes. One capture can therefore test **many settings at once**, one per control, and
`slcfg diff` labels each changed byte with its record and field (`r08+17` = pot 1, field +17).
Header settings get distinctive values instead (channel 5 vs. channel 9), so each byte can
only be explained one way.

## Setup (once)

1. Connect the SL by USB. Use the **ReMOTE SL Port 1** pair. Run `uv run slcfg ports` to check
   the names.
2. On the SL: **Global → page 4 → Ports** = `U1` (where dumps are sent).
3. On the SL: **Global → Memory Protect = OFF** (only needed for capture C12).
4. Make the capture folder: `mkdir -p dumps/captures`.

**How to take one capture** (repeat for each step):

```sh
uv run slcfg receive --device "ReMOTE SL Port 1" -o dumps/captures/C<n>.syx --timeout 60
# then on the SL: GLOBAL → scroll to page 4 → encoder 1 = "Current" → press button 1
uv run slcfg diff dumps/captures/C1.syx dumps/captures/C<n>.syx
```

"Current" dumps the **edit buffer**, so you never press WRITE: make the edits, dump, then
select another template and come back to discard them. Name each control you touch with the
capture number (e.g. `C2 E1`). That also confirms the name field.

Unless a step says otherwise, work on template **36 (User2)**. It is empty, and the factory
version is in `dumps/community/novation-factory-os41/36_-_-_User2.syx` to compare against.

---

## Checklist

### ☐ C0 – Full backup (do this first)
Global p4 → **All** (button 2). Save as `C0_all.syx` with `--count 40 --timeout 120`.
- Backs up all 40 templates before anything else.
- Checks header byte 7 = `01` on bulk members and shows bytes 9–10 for a live "All" dump.
- `slcfg diff` against `dumps/community/novation-factory-os41/bulk/…OS41.syx` shows any
  templates you changed over the years.

### ☐ C1 – Baseline
Select template 36, touch nothing, dump **Current** → `C1.syx`. Then dump **36** (by number) → `C1b.syx`.
- Diff C1 vs the factory `User2` file and C1 vs C1b: do bytes 7, 9–10 or 12 differ between a
  "Current" and a numbered dump? (FORMAT §1, bytes 9–10 guess)

### ☐ C2 – Channel and port codes (+18, +19)
Set every touched control to **Control = CC** first.

| Control | Setting |
|---|---|
| Encoder 1..5 | MidiChan = 1, 2, 16, KeybCHAN, ComnCHAN |
| Encoder 6 | only Control = CC (fresh CC defaults) |
| Pot 1..8 | Ports = OFF, U1, U2, U3, M1, M2, KeybPORT, ComnPORT |
| Slider 1..8 | Ports = U1 M1, U2 M1, U3 M1, U1 M2, M1 M2, U1 M1 M2, U3 M1 M2, U2 M2 |

Resolves H-chan and H-port (bit layout of +18/+19), and the CC default record.

### ☐ C3 – Template menu (header 97–108)
Template menu page 1: VelCurve = **SOFT 1**, AfterTch = **OFF**, KeybChan = **5**,
KeybPort = **M1**, ComnChan = **9**, ComnPort = **U2 M2**, PotMode = **PICK-UP**.
Page 2: Position = **2**, Size = **3**.
- Distinctive values map each setting to one header byte; group size/position re-checks 65/66.

### ☐ C4 – Ranges, display types, response, byte order
| Control | Setting |
|---|---|
| Encoder 1..5 | DispType = -64/+63, REL1, REL2, 0-16K, APOT (all CC) |
| Encoder 4 (0-16K) | also LowVal = **300**, HighVal = **9000** |
| Encoder 6 | CC, LowVal = 10, HighVal = 100 |
| Pot 1..4 | Response = JUMP, PICK-UP, TEMPLATE, GLOBAL |
| Slider 1 | LowVal = 127, HighVal = 0 (inverted) |
| Slider 2 | turn it to about the middle before dumping (stored value +20/+21) |

- 300 = `02 2C` MSB-first or `2C 02` LSB-first, so this settles the 14-bit byte order (FORMAT §1).
- Gives the DispType code table (+15) and finds where Response lives (+13/+14 guess).

### ☐ C5 – Buttons, button types, every message type (+8, +13, +22)
| Control | Setting |
|---|---|
| Button row 1, 1..4 | CC with BtnType = NORMAL, MOMENTRY, TOGGLE, STEP (StepVal = **5**) |
| Button row 1, 5..6 | CC with DispType = ON/OFF, LED |
| Button row 1, 7 | Control = NoContrl, DispType = LABEL, name `C5 LBL` |
| Button row 2, 1 | NOTE: note C3, velocity 100, MOMENTRY |
| Button row 2, 2 | PROG CHG: LowProg 5, HighProg 10, STEP |
| Button row 2, 3 | BANK CHG: MSB-LSB, Banklsb 3, Bankmsb 7 |
| Button row 2, 4 | REALTIME: Low RT-Start, High RT-Stop, TOGGLE |
| Button row 2, 5 | TEMPLATE: 12 |
| Button row 2, 6 | MMC: DEF PLAY, DeviceID 5 |
| Button row 2, 7 | NRPN: msb 3, lsb 4 |
| Button row 2, 8 | RPN: msb 0, lsb 5 |

- Confirms type codes 7/8/9 (PROG/BANK/REALTIME, FORMAT §3.3), the button-type bits, StepVal
  at +22, where note velocity / bank mode / realtime codes are stored, and whether TEMPLATE is
  stored 1-based.

### ☐ C6 – Pads, touchpad, pedals, joystick
| Control | Setting |
|---|---|
| Pad 1..3 | DRUMNOTE note 36; Auto-Off = NONE, **10 ms**, **1000 ms** |
| Pad 4 | DRUMNOTE, Off Sync = 1/4 note |
| Pad 5..6 | CC with BtnType = VELOCITY, TOGGLE |
| Touchpad X1, Y1, X2, Y2 | TchMode = HomeLeft, HomeUp, HomeCntr, HOLD |
| Touchpad Y2 | also Control = PITCHBND |
| Sustain | BtnType = TOGGLE |
| Expression | Response = PICK-UP |
| Joystick X | Control = CC 3 (not pitch bend) |

- Finds Auto-Off (14 bits: 1000 = `07 68`) and Off Sync, TchMode (+14 guess) and the pad
  VELOCITY code.

### ☐ C7 – SysEx block (+26..+40)
| Control | Setting |
|---|---|
| Encoder 1 | SYSEX, Length 6, SINGLE, DataPsn 4, bytes `7D 01 02 DV 03 04` |
| Encoder 2 | SYSEX, ROLAND, length 10 |
| Encoder 3 | SYSEX, DispType 0-16K, LSB-MSB, Length 6, DataPsn 2 |
| Encoder 4 | same as 3 but MSB-LSB |
| Encoder 5 | SYSEX, NONE, Length 3, bytes `7D 10 11` |

- Confirms the DataType codes (ROLAND / LSB-MSB / MSB-LSB are unseen) and how DV/CS
  placeholders are stored.

### ☐ C8 – Keyboard zones (header 112–151)
Template → Template (press twice) → Keyboard Zones: Zones = ON.
Zone 1: Low C1, High B2, Transpose +5, VelCurve HARD 1, MidiChan 3, Ports M2.
Zone 2: Low C3, High C5, Transpose −12, MidiChan 4, Ports U1 M1. Page 2: zone 2 AfterTch OFF,
PitchBnd ON, ModWheel OFF; PitchBnd & ModWheel = USE ZONE CHAN PORTS.
- Maps the four 10-byte zone blocks.

### ☐ C9 – State saved with the template (header 105–108?)
Rows: select **pots** on the left and **sliders** on the right. Press OCTAVE ▲ once. With the
DATA/SELECT encoder send bank 3 and then program 17. Dump.
- Manual §17 says a save stores rows, octave, bank and program. Finds where.

### ☐ C10 – Extra records 78–89
Hold **EDIT** and press, one at a time: each ROW-SELECT button, the four SCROLL buttons,
TAP TEMPO, OCTAVE ▲/▼. For any that opens an edit page, set CC **100 + n**, name `XTRA n`.
Dump.
- If records 78–89 change, they are the row-select/scroll assignments. If nothing is
  editable, write that down: they are Automap-only.

### ☐ C11 – Globals and identity (format side quests)
1. Global p4 → **Send Globals** → `C11_globals.syx` (a second message format, kept for later).
2. Optional, with SysEx Librarian (free): send a Universal Identity Request
   `F0 7E 7F 06 01 F7` to ReMOTE SL Port 2 (Global p3 IDPorts = U2) and save the reply. It
   may show the OS version, which bytes 9–10 might encode.

### ☐ C12 – Write path (the only capture that SENDS)
1. `uv run slcfg decode dumps/captures/C1.syx -o /tmp/c12.json`
2. In the JSON set `controls.encoder_1` to `{"name": "C12 OK", "type": "cc", "number": 74}`
   (keep `_raw`), or use `uv run slcfg tui dumps/captures/C1.syx --device "ReMOTE SL Port 1"`.
3. `uv run slcfg encode /tmp/c12.json -o /tmp/c12.syx`
4. `uv run slcfg send /tmp/c12.syx --device "ReMOTE SL Port 1"` → answer **y**.
5. On the SL: check the LCD shows `C12 OK` and encoder 1 sends CC 74 (MIDI monitor). Dump
   **Current** → `C12.syx`; `slcfg diff /tmp/c12.syx dumps/captures/C12.syx` should be empty.
- Proves the device accepts our encoder (no hidden checksum). Do not press WRITE unless
  you want to keep it.

---

## Afterwards

1. Commit `dumps/captures/` with one sidecar line per file: what you changed.
2. Push. The next session will update `docs/FORMAT.md` and `codec.py` and close the matching
   GitHub issues.
3. Restore anything you changed from `C0_all.syx` (`slcfg send` sends all 40 messages). Check
   on the SL whether a bulk send is stored directly or each template needs WRITE, and note it.
