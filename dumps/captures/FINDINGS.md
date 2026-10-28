# Capture findings

## C0 Full backup (do this first) (#8)
Files: C0_all.syx  ·  2026-10-27T16:17:36+00:00
Notes: OS 4.2.02. Byte-identical to backup_all.syx (dumps are deterministic). All 40 arrived within ~3 s of pressing retry: the port buffered the Dump All sent while the wizard sat at the retry prompt.

- · received 40 message(s)
- ✔ bulk flag (byte 7) values: [1]
- ★ header bytes 9-10 on a live 'All' dump: 22 02
- · 14 slot(s) differ from factory: ['Digitakt', 'Digitakt', 'CH-3', 'CH-4', 'CH-5', 'CH-6', 'CH-7', 'CH-8']

## C1 Baseline (#8)
Files: C1.syx  ·  2026-10-27T16:23:38+00:00
Notes: Template 35 (User1) used instead of 36: slot 36 holds JV-1010 on this SL. vs slot 35 in C0: byte7 01->00; r00/r16/r17 +14 00->10 (factory value); r56/57/58 +21 7F/4E/5D->00.

- · template 'User1' in slot 35
- ★ 'Current' dump header bytes 7..12: 00 00 22 02 00 22

## C1b Baseline, numbered dump (#8)
Files: C1b.syx  ·  2026-10-27T16:24:30+00:00
Notes: Dumped slot 35 by number. Identical to C0 slot 35 except byte 7 (01->00). So numbered dump = stored template; Current (edit buffer) differs: E1/S1/S2 +14 = 10 (stored 00), pads K1-K3 +21 = 00 (stored 7F/4E/5D).

- ✔ numbered dump has the same header as 'Current'

## C2 Channel and port codes: not captured

## C3 Template menu: not captured

## C4 Ranges, display types, response, byte order: not captured

## C5 Buttons and every message type: not captured

## C6 Pads, touchpad, pedals, joystick: not captured

## C7 SysEx block: not captured

## C8 Keyboard zones: not captured

## C9 State saved with the template: not captured

## C10 Extra records 78-89: not captured

## C11 Global settings: not captured

## C12 Write path (sends to the SL): not captured
