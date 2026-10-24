"""Decorative, lightly animated parts of the front panel.

Everything here is cosmetic. Widgets expose ``tick(t)`` (t in seconds); :class:`FrontPanel`
drives them from one timer, and skips the timer when Textual animations are off
(``TEXTUAL_ANIMATIONS=none``) so tests and slow terminals get a static panel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.color import Color
from textual.strip import Strip
from textual.widget import Widget

NEON = Color.parse("#39ff14")  # the Limited Edition's print green
NEON_DIM = Color.parse("#0b3a08")
LCD_TEXT = Color.parse("#9ad4ff")
LCD_TOP = Color.parse("#123a66")
LCD_BOTTOM = Color.parse("#081f3a")
LED_ON = Color.parse("#ff3b1f")
LED_OFF = Color.parse("#3a1410")
PANEL_BG = Color.parse("#101010")


def mix(a: Color, b: Color, f: float) -> str:
    return a.blend(b, max(0.0, min(1.0, f))).hex


def breathe(t: float, period: float = 3.0, phase: float = 0.0) -> float:
    """0..1 smooth pulse."""
    return 0.5 + 0.5 * math.sin(2 * math.pi * (t / period) + phase)


class Animated(Widget):
    """Base for widgets that redraw on :meth:`tick`."""

    t: float = 0.0

    def tick(self, t: float) -> None:
        self.t = t
        self.refresh()


# ---- green dot prints ------------------------------------------------------------------------


@dataclass(frozen=True)
class Dot:
    x: int
    y: int
    char: str
    phase: float


def spiral_dots(width: int, height: int) -> list[Dot]:
    """A sunflower spiral like the one printed at the SL's front-right corner, with a
    trail of smaller dots drifting up from it.

    Cells are about twice as tall as wide, so x is stretched to keep it round.
    """
    max_r = min(width / 4, height / 2) - 0.5
    cx, cy = width / 2, height - max_r - 1
    dots: dict[tuple[int, int], Dot] = {}
    golden = math.pi * (3 - math.sqrt(5))
    n = 42
    for i in range(n):
        r = max_r * math.sqrt(i / n)
        a = i * golden
        x, y = round(cx + 2 * r * math.cos(a)), round(cy + r * math.sin(a))
        if 0 <= x < width and 0 <= y < height and (x, y) not in dots:
            size = r / max_r
            char = "●" if size > 0.66 else "•" if size > 0.33 else "·"
            dots[(x, y)] = Dot(x, y, char, a)
    # sparse trail above the spiral, thinning out towards the rear
    for k, y in enumerate(range(int(cy - max_r) - 1, -1, -1)):
        for x in range(1 + (k * 5) % 3, width, 3 + k // 3):
            if (x * 7 + y * 3) % 5 == 0:
                dots.setdefault((x, y), Dot(x, y, "•" if k < 4 else "·", x * 0.5 + y))
    return list(dots.values())


def scatter_dots(width: int, height: int) -> list[Dot]:
    """The loose dot cluster around the logo (top-left of the unit)."""
    pattern = [
        "●   •  ·    ·",
        "  ●    •  ·  ",
        " •  ●     ·  ",
        "●  •   ·   · ",
    ]
    out = []
    for y, line in enumerate(pattern[:height]):
        for x, ch in enumerate(line[:width]):
            if ch != " ":
                out.append(Dot(x, y, ch, (x * 0.7 + y * 1.3)))
    return out


class DotField(Animated):
    """Neon-green dots on the black panel; a slow wave of brightness runs through them."""

    DEFAULT_CSS = "DotField { background: #101010; }"

    def __init__(self, kind: str = "spiral", **kw) -> None:
        super().__init__(**kw)
        self.kind = kind
        self._dots: list[Dot] = []
        self._grid_size = (0, 0)

    def _layout(self) -> None:
        w, h = self.size.width, self.size.height
        if (w, h) != self._grid_size:
            self._grid_size = (w, h)
            self._dots = spiral_dots(w, h) if self.kind == "spiral" else scatter_dots(w, h)

    def render_line(self, y: int) -> Strip:
        self._layout()
        w = self.size.width
        cells = [Segment(" ", Style(bgcolor=PANEL_BG.hex))] * w
        for d in self._dots:
            if d.y == y:
                glow = breathe(self.t, 4.0, d.phase)
                cells[d.x] = Segment(
                    d.char,
                    Style(color=mix(NEON_DIM, NEON, 0.35 + 0.65 * glow), bgcolor=PANEL_BG.hex),
                )
        return Strip(cells, w)


# ---- LCD -------------------------------------------------------------------------------------


class Lcd(Animated):
    """Blue backlit LCD with two 72-character lines, as on the SL (8 cells of 9 chars).

    Shows names over values for the active control row, like Play mode on the hardware.
    """

    DEFAULT_CSS = "Lcd { height: 3; }"

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.lines = ["", "", ""]

    def show(self, top: str, bottom: str, caption: str = "") -> None:
        self.lines = [top, bottom, caption]
        self.refresh()

    def render_line(self, y: int) -> Strip:
        w = self.size.width
        h = max(self.size.height, 1)
        text = self.lines[y] if y < len(self.lines) else ""
        text = text[:w].ljust(w)
        base = LCD_TOP.blend(LCD_BOTTOM, y / max(h - 1, 1))
        # a soft band of light drifting across the glass
        sweep = (self.t / 9.0) % 1.6 - 0.3
        fg = LCD_TEXT if y < 2 else LCD_TEXT.blend(LCD_BOTTOM, 0.55)
        segs = []
        for x, ch in enumerate(text):
            d = abs(x / max(w - 1, 1) - sweep)
            bg = base.blend(Color(120, 190, 255), max(0.0, 0.12 - d * 0.5))
            segs.append(Segment(ch, Style(color=fg.hex, bgcolor=bg.hex, bold=y == 0)))
        return Strip(segs, w)


# ---- row-select LED --------------------------------------------------------------------------


class Led(Animated):
    """The small LED next to a ROW-SELECT button; lit for the row shown on the LCD."""

    DEFAULT_CSS = "Led { width: 2; height: 3; }"

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.lit = False

    def set_lit(self, lit: bool) -> None:
        self.lit = lit
        self.refresh()

    def render_line(self, y: int) -> Strip:
        w = self.size.width
        bg = PANEL_BG.hex
        if y != 1:
            return Strip([Segment(" " * w, Style(bgcolor=bg))], w)
        color = (
            mix(LED_OFF, LED_ON, 0.75 + 0.25 * breathe(self.t, 2.2)) if self.lit else LED_OFF.hex
        )
        return Strip([Segment("●", Style(color=color, bgcolor=bg)), Segment(" " * (w - 1))], w)


# ---- shimmering wordmark -----------------------------------------------------------------------


class Wordmark(Animated):
    """Text lines with a green highlight sweeping through them."""

    DEFAULT_CSS = "Wordmark { background: #101010; }"

    def __init__(self, lines: list[str], **kw) -> None:
        super().__init__(**kw)
        self.lines = lines

    def render_line(self, y: int) -> Strip:
        w = self.size.width
        text = (self.lines[y] if y < len(self.lines) else "").center(w)[:w]
        sweep = (self.t / 5.0) % 2.0 * w - w / 2
        segs = []
        for x, ch in enumerate(text):
            near = max(0.0, 1 - abs(x + y * 2 - sweep) / 6)
            color = mix(Color.parse("#2bd10f"), Color.parse("#d8ffcf"), near * 0.8)
            segs.append(Segment(ch, Style(color=color, bgcolor=PANEL_BG.hex, bold=y == 0)))
        return Strip(segs, w)


# ---- keys ------------------------------------------------------------------------------------


def keyboard_art(octaves: int = 3, white_w: int = 7, height: int = 6) -> Text:
    """37 keys (C..C): black keys over the top 4 lines, shaded like real keytops."""
    whites = octaves * 7 + 1
    black_after = {0, 1, 3, 4, 5}  # C#, D#, F#, G#, A# follow these white keys (mod 7)
    width = whites * white_w
    white_top, white_bottom = Color.parse("#f6f6f2"), Color.parse("#b9b9b4")
    black_top, black_bottom = Color.parse("#3a3a3a"), Color.parse("#050505")
    rows: list[Text] = []
    for line in range(height):
        f = line / max(height - 1, 1)
        wbg = white_top.blend(white_bottom, f * f).hex
        bbg = black_top.blend(black_bottom, min(1.0, line / 3)).hex
        t = Text()
        for x in range(width):
            k, pos = divmod(x, white_w)
            in_black = line < 4 and (
                (pos >= white_w - 2 and k % 7 in black_after and k < whites - 1)
                or (pos <= 1 and k > 0 and (k - 1) % 7 in black_after)
            )
            if in_black:
                t.append("▔" if line == 3 else " ", style=f"#000000 on {bbg}")
            elif pos == white_w - 1:
                t.append("▏", style=f"#8a8a86 on {wbg}")
            else:
                t.append(" ", style=f"on {wbg}")
        rows.append(t)
    return Text("\n").join(rows)
