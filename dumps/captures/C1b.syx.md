# C1b.syx: C1b Baseline, numbered dump

Settings changed on the SL:

    Still on template 36, touch nothing.
    This time dump by NUMBER: GLOBAL → page 4 → encoder 1 = 36 → button 1.

Dumped with: GLOBAL → page 4 → encoder 1 = 36 → press button 1

Notes: Dumped slot 35 by number. Identical to C0 slot 35 except byte 7 (01->00). So numbered dump = stored template; Current (edit buffer) differs: E1/S1/S2 +14 = 10 (stored 00), pads K1-K3 +21 = 00 (stored 7F/4E/5D).

Findings:

- ✔ numbered dump has the same header as 'Current'
