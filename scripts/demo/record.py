"""Record docs/demo.gif: a short loop of the editor driven by Textual's pilot.

    uv run python scripts/demo/record.py          # needs node + playwright, ffmpeg

Frames are exported as SVG by Textual, rasterised by headless Chromium (svg2png.js) and
assembled into a looping GIF by ffmpeg. The fake MIDI port is used; nothing is sent.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from textual.widgets import Input

from slcfg import midi_io
from slcfg.tui.app import SLConfigApp

ROOT = Path(__file__).resolve().parents[2]
# relative, so the recording shows a repo path rather than this machine's
TEMPLATE = Path("dumps/community/novation-factory-os41/01_-_Novation_-_V-Station-1.syx")
OUT = ROOT / "docs/demo.gif"
SIZE = (198, 54)
FPS = 8
STEP = 1 / FPS


async def record(frames: Path) -> int:
    app = SLConfigApp(path=TEMPLATE, port=midi_io.FakeMidiPort())
    n = 0

    async with app.run_test(size=SIZE) as pilot:

        async def hold(seconds: float) -> None:
            nonlocal n
            for _ in range(max(1, round(seconds * FPS))):
                await pilot.pause(STEP)
                (frames / f"{n:04d}.svg").write_text(app.export_screenshot())
                n += 1

        async def type_into(selector: str, text: str) -> None:
            field = app.query_one(selector, Input)
            field.value = ""
            for ch in text:
                field.value += ch
                await hold(STEP * 1.5)

        await hold(1.5)  # idle: dots breathe, LCD glows
        await pilot.click("#ctl-pot_2")  # left LCD -> POTS, LED moves
        await hold(1.25)
        await pilot.click("#ctl-slider_3")  # right LCD -> SLIDERS
        await hold(1.0)
        await pilot.click("#ctl-encoder_1")
        await hold(0.5)
        await type_into("#f-name", "Cutoff")
        await type_into("#f-number", "74")
        await hold(0.4)
        await pilot.click("#apply")  # panel label + LCD update
        await hold(1.5)
        app.query_one("#previews").active = "tab-diff"
        await hold(1.75)
        await pilot.click("#send")  # confirmation dialog
        await hold(1.25)
        await pilot.click("#confirm-yes")
        await hold(1.75)
    return n


def main() -> None:
    os.chdir(ROOT)
    for tool in ("node", "ffmpeg"):
        if not shutil.which(tool):
            sys.exit(f"{tool} is required")
    with tempfile.TemporaryDirectory() as tmp:
        frames = Path(tmp)
        n = asyncio.run(record(frames))
        subprocess.run(
            ["node", str(Path(__file__).with_name("svg2png.js")), str(frames)], check=True
        )
        palette = frames / "palette.png"
        scale = "scale=1200:-1:flags=lanczos"
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(FPS),
                "-i",
                str(frames / "%04d.png"),
                "-vf",
                f"{scale},palettegen=stats_mode=diff",
                str(palette),
            ],
            check=True,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(FPS),
                "-i",
                str(frames / "%04d.png"),
                "-i",
                str(palette),
                "-lavfi",
                f"{scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                "-loop",
                "0",
                str(OUT),
            ],
            check=True,
        )
    print(f"{n} frames -> {OUT} ({OUT.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
