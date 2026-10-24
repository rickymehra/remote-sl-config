# Decisions log

Small calls made without the owner, newest last. Change any of them freely.

| # | Decision | Why |
|---|---|---|
| 1 | Python 3.12+, `uv`, hatchling build, `src/` layout, entry point `slcfg` | As requested; hatchling is uv's default backend |
| 2 | Extra module `analysis.py` (inspect/stride heuristics) next to the requested files | Keeps `sysex.py` free of guesswork and `cli.py` thin |
| 3 | CI installs `libasound2-dev` on Ubuntu | `python-rtmidi` has no Linux wheel for our Python, so it compiles against ALSA. macOS uses wheels |
| 4 | Community dumps are committed unmodified, with sidecars stating the license is unknown | They are tiny, freely distributed by Novation / the author, and are the evidence for FORMAT.md. Remove on request |
| 5 | oldgearguy's TX802 set (made for the **ZeRO SL Mk1**) is kept with the Mk1 dumps | Same header, length and record layout, byte for byte. Noted in its sidecars |
| 6 | No MkII / Compact dumps were collected | None turned up during the search; nothing to reject |
| 7 | The codec only rewrites fields whose value changed, starting from `_raw` | Makes `encode(decode(x)) == x` true by construction, even for fields we misread |
| 8 | Uncertain fields (`channel`, `port`, `display`, unknown type/button codes) are raw integers or `type_N` / `bits_N` | Better than a friendly name that might be wrong; edits stay one byte |
| 9 | JSON `slot` is 1-based (1..40), as on the SL display; the SysEx byte is 0-based | Matches the device UI |
| 10 | JSON keys name physical controls (`encoder_1`, `button_row3_2`, `touchpad_x1`) | Stable and readable. Record numbers are in FORMAT.md |
| 11 | Button rows are numbered 1–4: left rear, left front, right rear, right front | Follows oldgearguy's layout sheet and the owner's photo |
| 12 | Records 78–89 are exposed as `extra_1..12` | Purpose unknown (FORMAT §3.1), but keeping them editable costs nothing |
| 13 | The TUI and CLI default to a fake port; real hardware only with `--device NAME` | As requested. The fake port is a loopback, so Receive can be tested |
| 14 | `send_template` needs a callback that returns exactly `True`; CLI asks with `typer.confirm`, TUI with a modal | Two independent guards. No `--yes` flag, so a send is never unattended |
| 15 | TUI validation: names ≤ 8 printable ASCII, new numeric input 0..127; 14-bit values from a dump are shown and kept as-is | Spec asks for 0–127; refusing to load existing 0-16K values would lose data |
| 16 | Multi-template files decode to `{"format": "slcfg-bundle/1", "templates": [...]}` | Bulk dumps round-trip through one JSON file |
| 17 | Pilot tests drive the TUI through `asyncio.run` (no pytest-asyncio) | One dependency fewer |
| 18 | `jsonschema` is a dev dependency, used to test the schema against every dump | Keeps the schema and the codec in sync |
| 19 | Header byte 7 is treated as a bulk-member flag but never rewritten | Unclear whether the SL cares when a bulk member is sent alone |
| 20 | TUI panel follows the hardware geometry (rear at top), with fixed-function parts (LCDs, row-selects, mode buttons, octave, jacks) drawn dimmed | Easier to find a control by where it is on the keyboard; a test locks the geometry |
| 21 | The control form moved under the panel; records 79–90 sit in a collapsed section | The panel needs about 180 columns; narrower terminals scroll it sideways |
| 22 | Panel decor (neon dot prints, LIMITED EDITION badge, green strip frames, backlit LCDs, row LEDs, shaded keys) is animated by one 8 fps timer | Subtle motion, cheap to redraw; off when `TEXTUAL_ANIMATIONS=none` |
| 23 | The LCDs show names over values of the selected control's row and light that row's LED, like Play mode | Same feedback as the hardware; values with display code 1 show as -64..+63 |
