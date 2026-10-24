# ReMOTE SL (Mk1) template SysEx format

Draft built from **129 templates**: 89 single-template files and one 40-template bulk dump
(see `dumps/community/`), plus the ReMOTE SL user guide (Edit mode, Template menu, Keyboard
Zones and Global menu chapters). No hardware captures yet; `docs/CAPTURE_PLAN.md` resolves
the guesses.

Confidence labels:

- **confirmed**: holds for every dump and has a check independent of the dumps (the manual,
  a template's purpose, a physical-layout source), or is pure structure that never varies.
- **likely**: consistent with every dump and with the manual, but no independent check yet.
- **guess**: a hypothesis that fits what we have. Codec handles these as raw codes.

The codec (`src/slcfg/codec.py`) implements exactly the offsets below. `RECORD_FIELDS` and
`HEADER_FIELDS` carry the same confidence labels.

## 1. Message framing

| Offset | Size | Value | Meaning | Confidence | Evidence |
|---|---|---|---|---|---|
| 0 | 1 | `F0` | SysEx start | confirmed | all files |
| 1–3 | 3 | `00 20 29` | Novation manufacturer ID | confirmed | all files; registered MMA ID |
| 4–6 | 3 | `02 03 7F` | product / message class | confirmed constant, meaning guess | identical in all 129 templates |
| 7 | 1 | `00` / `01` | `00` single dump, `01` member of an "All" bulk dump | likely | all 40 bulk members have `01`, all single files `00` |
| 8 | 1 | `00` | — | confirmed constant | |
| 9–10 | 2 | e.g. `21 09` | stamp that varies by **source pack**, not by content | guess | all 36 factory singles: `21 09`; bulk members: `21 07`; additional pack: `11 02`, `10 02`, `08 0A`, `08 0E`, `3B 03`; TX802: `22 02`. Same value on different bodies, so not a checksum. Maybe editor/OS build or transfer mode |
| 11 | 1 | `00` | — | confirmed constant | |
| 12 | 1 | 0–39 | **memory location, 0-based** | confirmed | factory files `01 …` to `36 …` hold `00`–`23`; bulk members `00`–`27`; TX802_1..7 hold `00`–`06` and the author says "load into positions 1-7" |
| 13–60 | 48 | ASCII | **template name**, space padded | confirmed | manual: "template name can be a maximum of 48 characters"; factory names put the maker in the last 13 chars (`V-Station-1 … Novation`) |
| 61–418 | 358 | | template settings (section 2) | mixed | |
| 419–4108 | 90 × 41 | | **control records** (section 3) | confirmed | |
| 4109–4110 | 2 | `12 34` | constant trailer | confirmed constant | identical in all 129 templates |
| 4111 | 1 | `F7` | SysEx end | confirmed | |

Total **4112 bytes**. A bulk dump is 40 of these messages back to back (164 480 bytes). Bulk
member bodies (bytes 13 onward) are byte-identical to the matching single files.

**Encoding.** Data are stored unpacked: every byte is already 7-bit (no 8-to-7 packing,
no nibbles; no byte ≥ `0x80` in any body). Values that can exceed 127 take two 7-bit bytes
(manual: ranges up to 16383, Auto-Off up to 16383 ms). **Byte order is a guess (MSB first)**.
The only full-range example in the dumps is `7F 7F` (16383, the `Pitch` encoder of Ableton
Live DJ01), which reads the same both ways. Capture C4 settles it with Low = 300.

**Checksum: likely none.** Every byte that varies between dumps belongs to a field, the
trailer is constant, and bytes 9–10 are shared by different bodies. oldgearguy also
hand-edited records (pads of type TEMPLATE with a SysEx payload, which the editor refuses)
and the device accepted them. A device-side round trip (capture C12) will confirm it.

## 2. Template settings (bytes 61–418)

Most of this block is zero or constant. The codec keeps all of it in `_raw.header` and
exposes only the named fields.

| Offset | Meaning | Confidence | Evidence |
|---|---|---|---|
| 61–64 | zero (64 is `05` in one file) | — | |
| 65 | **template group size** | confirmed | V-Station 1–3 → 3; TX802 → 7; MOTU "(3 templates)" set → 3, "(6 templates)" set → 6; ungrouped → 0 |
| 66 | **position in group** (1-based) | confirmed | V-Station-1/2/3 → 1/2/3; TX802_n → n; MOTU sets 1..3 / 1..6 |
| 67 | zero | | |
| 68–69 | `5A 29` | constant | all files |
| 82–96 | `19 00 01 00 21 00 09 00 39 00 11 00 29 00 31` | constant, meaning unknown | all files |
| 97 | 0–4, mostly 3 | guess: velocity curve index | Template menu page 1 lists VelCurve first |
| 98 | 5–7, mostly 5 | guess: aftertouch / octave? | |
| 100 | port code (`47`, `07`, `43`, `4B`) | guess: keyboard port | same code family as record byte +18 |
| 101 | 0, 1, 9, 15 | guess: a MIDI channel (0-based) | MicroTonic (drums) = 9 → channel 10; Live/Traktor = 15 |
| 102 | port code (`47`, `44`, `43`) | guess: common port | |
| 105–108 | small values | guess: PotMode, rows selected on save, octave | manual §17: a save also stores PotMode, selected rows and octave |
| 112–151 | 4 × 10-byte blocks | likely: **keyboard zones 1–4** | in each block: +2 = 0 (low note), +3 = 127 (high note), +4 = 64 (transpose 0 on a −64..+63 scale); manual §16 has 4 zones |
| 151–186 | mostly zero; 155–170 hold 8 pairs in 4 templates | unknown | |
| 187–418 | zero | — | |

## 3. Control records (bytes 419 + 41·n)

### 3.1 Record order (n = 0..89)

| n | Control | Confidence | Evidence |
|---|---|---|---|
| 0–7 | **encoders** 1–8 | likely | Pro Tools template names them `APot 1-8` (HUI V-pots are encoders); oldgearguy's layout sheet puts them in the knob row nearer the LCD |
| 8–15 | **pots** 1–8 | likely | the other knob row in the same sheet; physically between button row 2 and the pads (owner's photo) |
| 16–23 | **sliders** 1–8 | confirmed | Pro Tools: `Fader 1-8`; MIDI CC Learn template lists them separately; right half of the layout sheet |
| 24–31 | **button row 1** (left half, behind the encoders) | likely | layout sheet row 1 left; Pro Tools `VBtn` (V-pot select sits next to the V-pots) |
| 32–39 | **button row 2** (left half, between encoders and pots) | likely | layout sheet row 3 left; Pro Tools `Record 1-8` |
| 40–47 | **button row 3** (right half, in front of the sliders) | likely | layout sheet row 3 right; Pro Tools `Mute 1-8` |
| 48–55 | **button row 4** (right half, nearest the keys) | likely | layout sheet row 4 right; Pro Tools `Solo 1-8` |
| 56–63 | **drum pads** 1–8 | confirmed | 112 records of type DRUMNOTE and 42 of type TEMPLATE appear only here; the TX802 README describes its pads |
| 64 | **expression pedal** | confirmed | name `Expresn`/`EPedal`; CC 11 |
| 65 | **sustain pedal** | confirmed | name `Sustain`; CC 64; default button mode momentary, Low 127 High 0 |
| 66 | **joystick Y (mod)** | confirmed | CC 1, `ModWheel` |
| 67 | **joystick X (pitch)** | confirmed | the only record with type PITCHBND (manual: only the joystick X axis and touchpad may send pitch bend) |
| 68–71 | **touchpad X1, Y1, X2, Y2** | confirmed | Pro Tools `TPad X1/Y1/X2/Y2`; manual: 4 touchpad assignments |
| 72–77 | **transport** rewind, forward, stop, play, **record, loop** | confirmed | names; MMC command codes 05/04/01/02/06. Note: physical order is …play, loop, record |
| 78–89 | **12 extra records** | guess | 13 of 89 dumps name them. Pro Tools: `Edit Mix AltView S-Mute Compare Bypass RTZ END Spare×4`. No control in the manual's Edit-mode list is left over, so these may be assignments for the 12 non-assignable buttons (8 row-selects + 4 scrolls) used by Automap, or unused. Capture C11 |

Physical layout (owner's photo + oldgearguy's sheet), rear to front:

```
           LEFT HALF                          RIGHT HALF
 [touch- ] button row 1  (24-31)            sliders       (16-23)
 [ pad   ] encoders      ( 0-7 )            button row 3  (40-47)
 [joy-   ] button row 2  (32-39)            button row 4  (48-55)
 [ stick ] pots          ( 8-15)            transport     (72-77)
           drum pads     (56-63)
           ────────────────────── 37 keys ──────────────────────
```

### 3.2 Record fields (offset inside the 41-byte record)

| +Off | Size | Field | Confidence | Evidence / notes |
|---|---|---|---|---|
| 0–7 | 8 | **name** (ASCII, space padded) | confirmed | readable labels in every template; manual: 8 characters |
| 8 | 1 | **control type** | confirmed (see 3.3) | |
| 9–10 | 2 | **LowVal** (14-bit; +10 = low 7 bits is likely, +9 = high 7 bits is a guess) | likely | +10 holds: MMC command (05 rewind, 04 FF, 01 stop, 02 play, 06 record = the standard MMC codes); note number for NOTE/DRUMNOTE (pads 36..43); target template for TEMPLATE; Low 127 on ON/OFF buttons. +9 is 0 everywhere except the Pro Tools HUI `VBtn` buttons (`45`), where +9..+12 look like four separate HUI bytes |
| 11–12 | 2 | **HighVal** (same layout as LowVal) | likely | 127 by default; `7F 7F` on a 0-16K encoder; MMC device ID 127 (all-call); TX802 SysEx ranges 31/99/7 match the TX802 parameter ranges |
| 13 bits 2–4 | — | **button type** 0 NORMAL, 4 MOMENTARY (VELOCITY on pads), 8 TOGGLE, 16 STEP | likely | `ArpOnOff` lo 0x1C hi 0x1D = 8; octave/step buttons with a step value = 16; sustain pedal (momentary by default) = 4; Pro Tools drum pads = 4 (manual: VELOCITY replaces MOMENTARY on pads) |
| 13 bits 0,1,5,6 | — | unknown flags; bit 0 is common on buttons and joystick | guess | preserved |
| 14 | 1 | flag byte: `51`, `50`, `11`, `10`, `41`, `01`, `58`, `59`, `19`, `09` | guess | candidates: Response (JUMP/PICK-UP/TEMPLATE/GLOBAL), touchpad mode, Off Sync. Preserved. Capture C4/C6 |
| 15 | 1 | **DispType** | likely for 0/1, guess for the rest | 1 on bipolar parameters (Pan, Semi, Fine, FLfoAmt); 3 on ON/OFF buttons with Low=127/High=0; 6/7 on encoders sending 63/65 increments (REL modes); 2 on all MMC transport; 8/9/16–20 in Automap templates |
| 16 | 1 | **NRPN/RPN MSB** | likely | FL Studio NRPN `01 1E`; General MIDI RPN coarse/fine tune = MSB 0 |
| 17 | 1 | **CC number / NRPN LSB / RPN LSB** | confirmed | expression 11, sustain 64, mod 1; GM template RPN `Crs Tune` = 2, `FineTune` = 1 (RPN 0/2, 0/1); V-Station NRPN LSBs 0x68–0x6A |
| 18 | 1 | **port routing code** | guess | values `47`, `0F`, `07`, `45`, `41`, `4F`, `04`, `00`, `20`. Hypothesis H-port: bits 0–1 = USB port (0 none, 1 U1, 2 U2, 3 U3), bit 2 = M1, bit 3 = M2, bit 6 = follow ComnPORT, bit 5 = follow KeybPORT. Codec exposes the raw code |
| 19 | 1 | **MIDI channel code** | guess | `40` most common, `00`, `41`, `42`, `4F`, `30`, `20`. Hypothesis H-chan: low nibble = channel − 1, bit 6 = ComnCHAN, bit 5 = KeybCHAN. Codec exposes the raw code |
| 20–21 | 2 | **stored control value** (two 7-bit bytes, order as LowVal) | likely | manual §17: a save stores each control's current value. V-Station: 64 on bipolar knobs, NRPN `Osc1octv` 0x12 lies within its 0x10–0x13 range |
| 22 | 1 | **StepVal** | likely | non-zero (2, 5, 9, 14, 31, 32, 63) almost only on buttons with button type STEP |
| 23 | 1 | zero in all dumps | — | |
| 24 | 1 | unknown | guess | non-zero only in Pro Tools / Ableton DJ templates (often equals +10). Maybe Automap or Auto-Off related |
| 25 | 1 | zero in all dumps | — | |
| 26 | 1 | **SysEx DataType** (0 NONE, 1 SINGLE, others: ROLAND, LSB-MSB, MSB-LSB) | likely | TX802 = 1 with a variable byte; GarageBand transport = 0 (fixed message) |
| 27 | 1 | **SysEx length** (0–12) | likely | TX802 `43 10 01 06 vv` → 5; GarageBand `7D 02` → 2. Holds 1 on most non-SysEx records (default) |
| 28 | 1 | **SysEx data position** (1-based) | likely | TX802 → 5 = position of `vv` |
| 29–40 | 12 | **SysEx bytes** without F0/F7; variable byte stored as `7F` | likely | manual: length 0–12, so exactly 12 bytes fit. Ends the record at 41 |

### 3.3 Control type codes (+8)

| Code | Type | Confidence | Evidence |
|---|---|---|---|
| 0 | NoContrl | confirmed | unnamed blank records |
| 1 | CC | confirmed | expression CC11, sustain CC64, mod CC1 |
| 2 | NRPN | confirmed | V-Station (NRPN-controlled synth), FL Studio |
| 3 | RPN | likely | General MIDI template: `Crs Tune`/`FineTune` with numbers 2/1 |
| 4 | SYSEX | confirmed | TX802 Yamaha strings `43 10 …`; GarageBand `7D xx` |
| 5 | MMC | confirmed | transport records, MMC command codes |
| 6 | NOTE | confirmed | Resolume / Ableton DJ buttons with note numbers |
| 7 | PROG CHG | guess | not seen; manual lists it after NOTE |
| 8 | BANK CHG | guess | not seen |
| 9 | REALTIME | guess | not seen |
| 10 | PITCHBND | confirmed | only record 67 |
| 11 | DRUMNOTE | confirmed | only on pads; notes 36–43 |
| 12 | TEMPLATE | confirmed | TX802 pads switch to template n (README) |

The manual lists types in the order CC, NRPN, RPN, SYSEX, MMC, NOTE, PROG CHG, BANK CHG,
DRUMNOTE, TEMPLATE, REALTIME, PITCHBND. Codes 1–6 follow that order and 10–12 do not, so
7–9 stay guesses until capture C5.

## 4. What the codec does with unknowns

- Every record keeps its original 41 bytes in `_raw`; the header and trailer keep theirs in
  `_raw.header` / `_raw.trailer`.
- A field is rewritten only when its decoded value changes, so unknown bits sharing a byte
  (e.g. +13) and stray bytes beyond the SysEx length survive edits.
- Codes without a name round-trip as `type_N` / `bits_N` strings or raw integers
  (`channel`, `port`, `display`).
- Templates created from scratch start from the factory "User" template header and the most
  common blank record.
