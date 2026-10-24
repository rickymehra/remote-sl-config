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
| 24 | Out of scope: Automap and firmware (OS) updates | Owner does not use them; the tool covers templates, backups and (later) global settings |
| 25 | `slcfg capture` wizard holds the step instructions; a test keeps its step list in sync with CAPTURE_PLAN.md | One command for the hardware session; the doc stays the readable reference |
| 26 | Controls touched in capture n are named `C<n> <code>` on the SL | Every capture double-checks the record order for free |
| 27 | `--simulate` builds dumps from our current guesses and is labelled SIMULATED everywhere | Lets the flow be rehearsed and tested; must never be mistaken for evidence |
| 28 | Library keeps slots as loaded; moving only rewrites the slot byte (12), never the bulk flag (7) | Unchanged library saves byte for byte; the device's use of byte 7 is unconfirmed |
| 29 | "Changed vs factory" compares encoded bytes from the name (13) on with the factory template in the same slot | Ignores framing, bulk flag and slot number; a moved template counts as changed |
| 30 | `move` reorders like a list; `swap` exchanges two slots (the TUI's up/down use `swap`) | Distinct, predictable operations |
| 31 | Two templates for one slot when loading is an error | Silent renumbering would change header bytes nobody asked to change |
| 32 | A slot opened from the library is written back to that slot on Apply/Save, even if the editor's slot field changed | Never overwrites another slot by accident; move templates on the library screen |
| 33 | Receive all merges arriving templates by slot and skips non-template messages | A partial dump does not wipe the rest of the library |
| 34 | `library.read_templates` has its own small JSON reader instead of importing the CLI | Keeps library logic free of typer/Textual |
| 35 | Sends and receives in the TUI run in worker threads; a running receive turns its button into Cancel | The UI stays live while waiting up to 2 minutes for the SL |
| 36 | Progress bars only for multi-template transfers (receive/send all, C0 backup, `--count` > 1) | A single 4 KB template is instant; a bar would only flicker |
| 37 | Library "changed vs factory" caches each template's encoding; `get()` drops the cache entry it hands out | Table refreshes went from ~0.7 s to instant; in-place edits after `get()` are still seen |
| 38 | TUI tests run with animations off (autouse fixture; `@pytest.mark.animated` opts back in) | Animation timers are irrelevant to most tests |
| 39 | `--device` takes the exact port name or a unique, case-insensitive part of it | OSes decorate port names (Linux adds client numbers); a typo lists the available ports |
| 40 | Real MIDI path is tested against virtual ports, required on macOS CI and skipped where no MIDI system exists | Catches bugs in mido/rtmidi/large-SysEx handling before the hardware session; not evidence about the SL itself |
| 41 | Automap lock: controls of Automap templates (name contains "Automap") are read-only in the TUI by default; `a` toggles | The template data has no Automap flag (most are plain CCs a DAW script listens for), so the lock uses the user guide's per-template free list plus keyboard-routed controls (port code 0x20); undocumented controls are locked to be safe |
