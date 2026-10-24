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

Only assignable controls are buttons (``#ctl-<slot key>``); fixed-function parts (mode
buttons, octave, jacks) are drawn dimmed for orientation. The LCDs work like Play mode:
names over values for the row the selected control is in, with the row's LED lit.
Decoration and animation live in ``decor.py``.
"""

from __future__ import annotations

import time

from textual.app import ComposeResult
from textual.color import Color
from textual.containers import Grid, Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Collapsible, Static

from ..model import SLOT_BY_KEY, SLOTS, Template
from .decor import (
    NEON,
    Animated,
    DotField,
    Lcd,
    Led,
    Wordmark,
    breathe,
    keyboard_art,
    mix,
)

CELL = 9  # columns per control: 8-char LCD name + 1 gap
FPS = 8

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


ROW_CAPTIONS = {
    "button_row1": "BUTTONS 1",
    "encoder": "ENCODERS",
    "button_row2": "BUTTONS 2",
    "pot": "POTS",
    "drum_pad": "DRUM PADS",
    "slider": "SLIDERS",
    "button_row3": "BUTTONS 3",
    "button_row4": "BUTTONS 4",
}
SELECT_DIM = "#8a5200"
FRAME_GREEN = NEON.blend(Color.parse("#101010"), 0.45).hex  # the green strip outlines
SELECT_BRIGHT = "#ffa62b"


def lcd_cells(t: Template, group: str) -> tuple[str, str]:
    """Names and values of one row, laid out 9 characters per control like the SL LCD."""
    names, values = [], []
    for i in range(1, 9):
        c = t.controls.get(f"{group}_{i}")
        if c is None or c.type == "none":
            names.append(" " * CELL)
            values.append(" " * CELL)
            continue
        names.append(c.name[:8].ljust(CELL))
        v = c.value - 64 if c.display == 1 else c.value
        values.append((f"{v:+d}" if c.display == 1 else str(v)).center(CELL - 1) + " ")
    return "".join(names), "".join(values)


class FrontPanel(Widget):
    """Every assignable SL control as a button, placed where it is on the hardware."""

    DEFAULT_CSS = f"""
    FrontPanel {{ height: auto; width: auto; background: #101010; }}
    FrontPanel .ctl {{
        width: {CELL - 1}; min-width: {CELL - 1}; height: 3; padding: 0; margin-right: 1;
        background: #2a2a2a; color: #e6e6e6;
    }}
    FrontPanel .ctl:hover {{ background: #3a3a3a; }}
    FrontPanel .ctl.selected {{ background: {SELECT_BRIGHT}; color: #101010; }}
    FrontPanel .fixed {{ color: #6b6b6b; height: 3; content-align: center middle; }}
    FrontPanel .row {{ height: 3; width: auto; }}
    FrontPanel Lcd {{ width: {8 * CELL}; }}
    FrontPanel .scroll {{ width: 2; }}
    FrontPanel #rear {{ height: 3; width: auto; background: #0a0a0a; }}
    FrontPanel #rear .fixed {{ width: auto; padding: 0 1; }}
    FrontPanel #rear .ctl {{ width: 12; }}
    FrontPanel #body {{ height: 20; width: auto; }}
    FrontPanel #left .row, FrontPanel #right .row, FrontPanel #sliders {{ width: {8 * CELL + 2}; }}
    FrontPanel .section {{
        height: 20; width: {8 * CELL + 2 + 2}; border: round {FRAME_GREEN};
        border-title-color: {NEON.hex}; border-title-style: bold;
    }}
    FrontPanel #far-left {{ width: 20; height: 20; }}
    FrontPanel #far-left .ctl {{ width: 9; }}
    FrontPanel #far-left Wordmark {{ height: 2; }}
    FrontPanel #far-left DotField {{ height: 4; }}
    FrontPanel #badge {{
        height: 4; width: 16; margin-left: 1; border: round {NEON.hex}; color: {NEON.hex};
        content-align: center middle; text-style: bold;
    }}
    FrontPanel #center {{ width: 11; height: 20; }}
    FrontPanel #center Wordmark {{ height: 3; }}
    FrontPanel #center .mode {{ height: 2; content-align: center middle; }}
    FrontPanel #center .data {{ height: 3; border: round #555555; }}
    FrontPanel #far-right {{ width: 14; height: 20; }}
    FrontPanel #sliders .ctl {{ height: 6; }}
    FrontPanel #sliders {{ height: 6; }}
    FrontPanel .oct {{ width: {2 * CELL}; }}
    FrontPanel #front {{ height: auto; width: auto; }}
    FrontPanel #touchpad {{
        width: 20; height: 6; grid-size: 2; grid-gutter: 0 0; grid-columns: 10;
        background: #1b1b1b;
    }}
    FrontPanel #touchpad .ctl {{ width: 9; }}
    FrontPanel #keys {{ height: 6; width: auto; }}
    FrontPanel Collapsible {{ width: auto; padding: 0; border: none; }}
    FrontPanel #extras {{ height: 3; width: auto; }}
    """

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.left_row = "encoder"
        self.right_row = "slider"
        self.selected: str | None = None
        self._t0 = time.monotonic()
        self.animating = False

    def compose(self) -> ComposeResult:
        # Rear edge: the pedals plug in here.
        with Horizontal(id="rear"):
            yield fixed("rear:  MIDI1 IN OUT THRU   MIDI2 OUT")
            yield ctl_button("expression")
            yield ctl_button("sustain")
            yield fixed("USB   9V DC")
        with Horizontal(id="body"):
            with Vertical(id="far-left"):
                yield Wordmark(["novation", "ReMOTE 37SL"])
                yield DotField("scatter")
                yield Static("LIMITED\nEDITION  Ⓐ", id="badge")
                yield DotField("scatter", id="dots-left-2")
                with Horizontal(classes="row"):
                    yield ctl_button("mod")
                    yield ctl_button("pitch")
                yield fixed("joystick")
            with Vertical(id="left", classes="section") as left:
                left.border_title = "Automap"
                with Horizontal(classes="row"):
                    yield fixed("◂▸", "scroll")
                    yield Lcd(id="lcd-left")
                for group in LEFT_ROWS:
                    with Horizontal(classes="row", id=f"row-{group}"):
                        yield Led(id=f"led-{group}")
                        for i in range(1, 9):
                            yield ctl_button(f"{group}_{i}")
            with Vertical(id="center"):
                yield Wordmark(["", "novation", ""])
                for name in MODE_BUTTONS:
                    yield fixed(name, "mode")
                yield fixed("DATA ◎", "data")
            with Vertical(id="right", classes="section") as right:
                right.border_title = "ReMOTE SL"
                with Horizontal(classes="row"):
                    yield Lcd(id="lcd-right")
                    yield fixed("◂▸", "scroll")
                with Horizontal(id="sliders"):
                    for i in range(1, 9):
                        yield ctl_button(f"slider_{i}", "slider")
                    yield Led(id="led-slider")
                for group in RIGHT_ROWS[1:]:
                    with Horizontal(classes="row", id=f"row-{group}"):
                        for i in range(1, 9):
                            yield ctl_button(f"{group}_{i}")
                        yield Led(id=f"led-{group}")
                with Horizontal(classes="row", id="row-transport"):
                    yield fixed("octave ◂ ▸", "oct")
                    for key in TRANSPORT_KEYS:
                        yield ctl_button(key)
            yield DotField("spiral", id="far-right")
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

    def on_mount(self) -> None:
        if self.app.animation_level != "none":
            self.animating = True
            self.set_interval(1 / FPS, self._tick)

    def _tick(self) -> None:
        t = time.monotonic() - self._t0
        for w in self.query(Animated):
            w.tick(t)
        if self.selected:
            btn = self.query_one(f"#ctl-{self.selected}", Button)
            btn.styles.background = mix(
                Color.parse(SELECT_DIM), Color.parse(SELECT_BRIGHT), 0.55 + 0.45 * breathe(t, 2.4)
            )

    def show(self, template: Template, selected: str) -> None:
        """Mark the selected control and update LCDs/LEDs the way the hardware would."""
        if self.selected and self.selected != selected:
            old = self.query_one(f"#ctl-{self.selected}", Button)
            old.styles.clear_rule("background")
            old.remove_class("selected")
        self.selected = selected
        self.query_one(f"#ctl-{selected}", Button).add_class("selected")
        group = SLOT_BY_KEY[selected].group
        if group in LEFT_ROWS:
            self.left_row = group
        elif group in RIGHT_ROWS:
            self.right_row = group
        for g in LEFT_ROWS + RIGHT_ROWS:
            self.query_one(f"#led-{g}", Led).set_lit(g in (self.left_row, self.right_row))
        for lcd_id, row in (("#lcd-left", self.left_row), ("#lcd-right", self.right_row)):
            names, values = lcd_cells(template, row)
            self.query_one(lcd_id, Lcd).show(names, values, f"  {ROW_CAPTIONS[row]}")
