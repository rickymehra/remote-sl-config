"""The ReMOTE SL front panel, laid out like the hardware.

Seen from the player, rear at the top (owner's photos + oldgearguy's layout sheet; the
record numbers are in docs/FORMAT.md):

    rear jacks:  MIDI1 IN OUT THRU  MIDI2 OUT  [EXPR] [SUST]  USB  PWR
    .........  ◂▸[ left LCD ]                 nov.  [ right LCD ]◂▸
    .........  ◂ button row 1  (8)            WRITE  sliders (8, tall)  ▸
    .........  ◂ encoders      (8)            TEMPL  "                  ▸
    .........  ◂ button row 2  (8)            EDIT   button row 3 (8)   ▸
    .........  ◂ pots          (8)            PLAY   button row 4 (8)   ▸
    .........  ◂ drum pads     (8)            DATA   oct◂▸ transport (6)
    [joystick]
    [touchpad]  ═══════════════════ 37 keys ═══════════════════════════

Only assignable controls are buttons (``#ctl-<slot key>``); fixed-function parts (row
select, scroll, mode buttons, LCDs, octave, jacks) are drawn dimmed for orientation.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Collapsible, Static

from ..model import SLOT_BY_KEY, SLOTS

CELL = 9  # columns per control: 8-char LCD name + 1 gap

# Rear-to-front rows of each half.
LEFT_ROWS = ["button_row1", "encoder", "button_row2", "pot", "drum_pad"]
RIGHT_ROWS = ["slider", "button_row3", "button_row4"]  # sliders span two rows of depth
# Transport as printed on the panel, left to right (record order differs: …play, record, loop).
TRANSPORT_KEYS = ["rewind", "forward", "stop", "play", "loop", "record"]
MODE_BUTTONS = ["WRITE", "TEMPLATE", "EDIT", "PLAY", "GLOBAL", "TAP TEMPO"]
EXTRA_KEYS = [s.key for s in SLOTS if s.group == "extra"]

# Short labels shown when a control has no name.
EMPTY_LABEL = {
    "encoder": "enc",
    "pot": "pot",
    "slider": "sld",
    "button_row1": "btn",
    "button_row2": "btn",
    "button_row3": "btn",
    "button_row4": "btn",
    "drum_pad": "pad",
}


def empty_label(key: str) -> str:
    s = SLOT_BY_KEY[key]
    if s.group in EMPTY_LABEL:
        return f"{EMPTY_LABEL[s.group]} {key.rsplit('_', 1)[1]}"
    return s.label


def ctl_button(key: str, *extra_classes: str) -> Button:
    b = Button(empty_label(key), id=f"ctl-{key}", classes=" ".join(("ctl", *extra_classes)))
    b.styles.line_pad = 0  # Button pads labels by 1 each side; we need all 8 columns
    return b


def fixed(text: str, *classes: str) -> Static:
    """A non-assignable part of the panel, shown for orientation only."""
    return Static(text, classes=" ".join(("fixed", *classes)))


def keyboard_art(octaves: int = 3, white_w: int = 7) -> Text:
    """37 keys (C..C) as text: 4 lines with black keys, 2 lines of white key fronts."""
    whites = octaves * 7 + 1
    black_after = {0, 1, 3, 4, 5}  # C#, D#, F#, G#, A# follow these white keys (mod 7)
    width = whites * white_w
    rows: list[Text] = []
    for line in range(6):
        t = Text()
        for x in range(width):
            k, pos = divmod(x, white_w)
            in_black = line < 4 and (
                (pos >= white_w - 2 and k % 7 in black_after and k < whites - 1)
                or (pos <= 1 and k > 0 and (k - 1) % 7 in black_after)
            )
            if in_black:
                t.append(" ", style="on #1a1a1a")
            elif pos == white_w - 1:
                t.append("▏", style="#777777 on #e8e8e8")
            else:
                t.append(" ", style="on #e8e8e8")
        rows.append(t)
    return Text("\n").join(rows)


class FrontPanel(Widget):
    """Every assignable SL control as a button, placed where it is on the hardware."""

    DEFAULT_CSS = f"""
    FrontPanel {{ height: auto; width: auto; }}
    FrontPanel .ctl {{
        width: {CELL - 1}; min-width: {CELL - 1}; height: 3; padding: 0; margin-right: 1;
    }}
    FrontPanel .ctl.selected {{ background: $accent; color: $text; }}
    FrontPanel .fixed {{ color: $text-disabled; height: 3; content-align: center middle; }}
    FrontPanel .row {{ height: 3; width: auto; }}
    FrontPanel .rowsel {{ width: 2; }}
    FrontPanel .lcd {{
        width: {8 * CELL}; height: 3; background: #0c2a4a; color: #6fb7ff;
        content-align: center middle;
    }}
    FrontPanel .scroll {{ width: 2; }}
    FrontPanel #rear {{ height: 3; width: auto; }}
    FrontPanel #rear .fixed {{ width: auto; padding: 0 1; }}
    FrontPanel #rear .ctl {{ width: 12; }}
    FrontPanel #body {{ height: 18; width: auto; }}
    FrontPanel #left, FrontPanel #right {{ height: 18; width: auto; }}
    FrontPanel #far-left {{ width: 20; height: 18; }}
    FrontPanel #far-left .ctl {{ width: 9; }}
    FrontPanel #brand {{ height: 12; color: #39ff14; content-align: center middle; }}
    FrontPanel #center {{ width: 11; height: 18; }}
    FrontPanel #center .mode {{ height: 2; content-align: center middle; }}
    FrontPanel #center .data {{ height: 3; border: round #555555; }}
    FrontPanel #center .brand {{ height: 3; color: #39ff14; }}
    FrontPanel #sliders .ctl {{ height: 6; }}
    FrontPanel #sliders {{ height: 6; }}
    FrontPanel .oct {{ width: {2 * CELL}; }}
    FrontPanel #front {{ height: auto; width: auto; }}
    FrontPanel #touchpad {{
        width: 20; height: 6; grid-size: 2; grid-gutter: 0 0; grid-columns: 10;
    }}
    FrontPanel #touchpad .ctl {{ width: 9; }}
    FrontPanel #keys {{ height: 6; width: auto; }}
    FrontPanel Collapsible {{ width: auto; padding: 0; border: none; }}
    FrontPanel #extras {{ height: 3; width: auto; }}
    """

    def compose(self) -> ComposeResult:
        # Rear edge: the pedals plug in here.
        with Horizontal(id="rear"):
            yield fixed("rear:  MIDI1 IN OUT THRU   MIDI2 OUT")
            yield ctl_button("expression")
            yield ctl_button("sustain")
            yield fixed("USB   9V DC")
        with Horizontal(id="body"):
            with Vertical(id="far-left"):
                yield Static("· • ●\n novation \n ReMOTE\n 37 SL\n● • ·", id="brand")
                with Horizontal(classes="row"):
                    yield ctl_button("mod")
                    yield ctl_button("pitch")
                yield fixed("joystick")
            with Vertical(id="left"):
                with Horizontal(classes="row"):
                    yield fixed("◂▸", "scroll")
                    yield Static("left LCD", classes="lcd")
                for group in LEFT_ROWS:
                    with Horizontal(classes="row", id=f"row-{group}"):
                        yield fixed("◂", "rowsel")
                        for i in range(1, 9):
                            yield ctl_button(f"{group}_{i}")
            with Vertical(id="center"):
                yield fixed("● nov", "brand")
                for name in MODE_BUTTONS:
                    yield fixed(name, "mode")
                yield fixed("DATA ◎", "data")
            with Vertical(id="right"):
                with Horizontal(classes="row"):
                    yield Static("right LCD", classes="lcd")
                    yield fixed("◂▸", "scroll")
                with Horizontal(id="sliders"):
                    for i in range(1, 9):
                        yield ctl_button(f"slider_{i}", "slider")
                    yield fixed("▸", "rowsel")
                for group in RIGHT_ROWS[1:]:
                    with Horizontal(classes="row", id=f"row-{group}"):
                        for i in range(1, 9):
                            yield ctl_button(f"{group}_{i}")
                        yield fixed("▸", "rowsel")
                with Horizontal(classes="row", id="row-transport"):
                    yield fixed("octave ◂ ▸", "oct")
                    for key in TRANSPORT_KEYS:
                        yield ctl_button(key)
        with Horizontal(id="front"):
            with Grid(id="touchpad"):
                for key in ("touchpad_x1", "touchpad_y1", "touchpad_x2", "touchpad_y2"):
                    yield ctl_button(key)
            yield Static(keyboard_art(), id="keys")
        with (
            Collapsible(title="Records 79-90 (purpose unknown)", collapsed=True),
            Horizontal(id="extras"),
        ):
            for key in EXTRA_KEYS:
                yield ctl_button(key)
