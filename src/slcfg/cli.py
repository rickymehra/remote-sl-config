"""Command-line entry point: ``slcfg <command>``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from . import analysis, codec, midi_io
from .diff import diff_views, format_diff
from .model import Template, ValidationError
from .sysex import VIEWS, SysexError, split_messages

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)

BUNDLE_FORMAT = "slcfg-bundle/1"


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as e:
        raise typer.BadParameter(f"cannot read {path}: {e}") from e


def _hex(data: bytes, limit: int = 16) -> str:
    s = data[:limit].hex(" ")
    return s + (" …" if len(data) > limit else "")


# ---- analysis -------------------------------------------------------------------------------


@app.command()
def inspect(
    file: Path,
    max_lag: Annotated[int, typer.Option(help="Largest record stride to try")] = 256,
    show_ascii: Annotated[bool, typer.Option("--ascii/--no-ascii")] = False,
) -> None:
    """Split FILE into SysEx messages and report header, ASCII runs, labels and strides."""
    data = _read(file)
    reports = analysis.inspect_bytes(data, max_lag=max_lag)
    typer.echo(f"{file}: {len(data)} bytes, {len(reports)} message(s)")
    for r in reports:
        msg = r.message
        typer.echo(f"\n[{r.index}] offset {msg.offset}, length {len(msg.data)}")
        typer.echo(f"  header       {_hex(msg.data, 13)}")
        typer.echo(f"  manufacturer {msg.manufacturer_id.hex(' ')} ({msg.manufacturer})")
        if len(msg.data) == codec.MESSAGE_LEN and msg.data.startswith(codec.PREFIX):
            t = codec.decode(msg.data)
            kind = "bulk member" if codec.is_bulk(t) else "single"
            typer.echo(f"  SL template  slot {t.slot}, {kind}, name {t.name!r}")
        typer.echo(
            f"  stride       autocorr {r.stride} (score {r.stride_score:.2f}), "
            f"label gap {r.label_stride}, record base {r.record_base}"
            if r.stride is not None
            else "  stride       n/a"
        )
        typer.echo(f"  labels       {len(r.labels)} candidate 8-char label(s)")
        for lab in r.labels[:12]:
            typer.echo(f"    {lab.offset:5d}  {lab.text!r}")
        if len(r.labels) > 12:
            typer.echo(f"    … {len(r.labels) - 12} more")
        if show_ascii:
            for run in r.ascii:
                typer.echo(f"  ascii {run.offset:5d}  {run.text!r}")


@app.command()
def stride(
    file: Path,
    top: Annotated[int, typer.Option(help="How many candidates to list")] = 5,
    lo: Annotated[int, typer.Option(help="Smallest stride")] = 4,
    hi: Annotated[int, typer.Option(help="Largest stride")] = 256,
) -> None:
    """Guess a fixed record size in FILE by autocorrelation."""
    for msg in split_messages(_read(file), strict=False):
        typer.echo(f"message @{msg.offset} ({len(msg.data)} bytes)")
        for lag, score in analysis.stride_scores(msg.data, lo, hi)[:top]:
            typer.echo(f"  stride {lag:4d}  score {score:.3f}")


@app.command()
def diff(
    a: Path,
    b: Path,
    view: Annotated[str, typer.Option(help=f"One of {', '.join(VIEWS)} or 'all'")] = "raw",
    skip: Annotated[int, typer.Option(help="Ignore this many leading bytes before the view")] = 0,
) -> None:
    """Byte-level diff of two dumps (hex, decimal, ASCII), with optional alternate views."""
    da, db = _read(a), _read(b)
    views = list(VIEWS) if view == "all" else [view]
    for v in views:
        if v not in VIEWS:
            raise typer.BadParameter(f"unknown view {v!r}")
        diffs = diff_views(da, db, v, skip)
        is_sl = v == "raw" and all(
            len(x) % codec.MESSAGE_LEN == 0 and x.startswith(codec.PREFIX) for x in (da, db)
        )
        typer.echo(f"== view: {v}")
        typer.echo(
            format_diff(diffs, record_base=codec.RECORD_BASE, stride=codec.RECORD_LEN)
            if is_sl
            else format_diff(diffs)
        )


# ---- codec ----------------------------------------------------------------------------------


def _templates_to_json(ts: list[Template]) -> dict[str, Any]:
    if len(ts) == 1:
        return ts[0].to_json()
    return {"format": BUNDLE_FORMAT, "templates": [t.to_json() for t in ts]}


def _json_to_templates(doc: dict[str, Any]) -> list[Template]:
    if doc.get("format") == BUNDLE_FORMAT:
        return [Template.from_json(t) for t in doc["templates"]]
    return [Template.from_json(doc)]


def load_templates(path: Path) -> list[Template]:
    """Load .syx or .json into templates."""
    if path.suffix.lower() == ".json":
        return _json_to_templates(json.loads(path.read_text()))
    return codec.decode_file(_read(path))


@app.command()
def decode(
    syx: Path,
    out: Annotated[Path | None, typer.Option("-o", "--out", help="Write JSON here")] = None,
) -> None:
    """Decode a template .syx (single or bulk) to JSON."""
    try:
        ts = codec.decode_file(_read(syx))
    except (codec.CodecError, SysexError) as e:
        raise typer.BadParameter(str(e)) from e
    text = json.dumps(_templates_to_json(ts), indent=2) + "\n"
    if out:
        out.write_text(text)
        typer.echo(f"wrote {len(ts)} template(s) to {out}")
    else:
        typer.echo(text, nl=False)


@app.command()
def encode(
    src: Path,
    out: Annotated[Path, typer.Option("-o", "--out", help="Write .syx here")],
) -> None:
    """Encode template JSON back to .syx."""
    try:
        ts = _json_to_templates(json.loads(src.read_text()))
        data = codec.encode_file(ts)
    except (ValidationError, codec.CodecError, KeyError, json.JSONDecodeError) as e:
        raise typer.BadParameter(str(e)) from e
    out.write_bytes(data)
    typer.echo(f"wrote {len(ts)} template(s), {len(data)} bytes to {out}")


# ---- device ---------------------------------------------------------------------------------


@app.command()
def ports() -> None:
    """List MIDI ports (needs a working mido/python-rtmidi backend)."""
    ins, outs = midi_io.list_ports()
    typer.echo("inputs:  " + (", ".join(ins) or "(none)"))
    typer.echo("outputs: " + (", ".join(outs) or "(none)"))


DeviceOpt = Annotated[
    str | None,
    typer.Option("--device", help="Real MIDI port name, e.g. 'ReMOTE SL Port 1'. Omit for fake."),
]


@app.command()
def send(file: Path, device: DeviceOpt = None) -> None:
    """Send a template (.syx or .json) to the device. Always asks for confirmation."""
    data = codec.encode_file(load_templates(file))
    port = midi_io.open_port(device)
    if device is None:
        typer.echo("No --device given: using the fake port, nothing leaves this computer.")
    try:
        n = midi_io.send_template(port, data, lambda s: typer.confirm(s, default=False))
    except midi_io.SendCancelled:
        typer.echo("cancelled, nothing sent")
        raise typer.Exit(1) from None
    finally:
        port.close()
    typer.echo(f"sent {n} message(s). On the SL press WRITE to store it (Memory Protect off).")


@app.command()
def receive(
    out: Annotated[Path, typer.Option("-o", "--out")],
    device: DeviceOpt = None,
    count: Annotated[int, typer.Option(help="Messages to wait for")] = 1,
    timeout: Annotated[float, typer.Option(help="Seconds to wait")] = 30.0,
) -> None:
    """Wait for SysEx dumped from the device and save it raw to OUT."""
    port = midi_io.open_port(device)
    try:
        msgs = midi_io.receive_dump(port, timeout=timeout, count=count)
    finally:
        port.close()
    if not msgs:
        typer.echo("nothing received")
        raise typer.Exit(1)
    out.write_bytes(b"".join(msgs))
    typer.echo(f"saved {len(msgs)} message(s) to {out}")


@app.command()
def tui(file: Annotated[Path | None, typer.Argument()] = None, device: DeviceOpt = None) -> None:
    """Open the template editor."""
    from .tui.app import SLConfigApp

    SLConfigApp(path=file, device=device).run()


if __name__ == "__main__":  # pragma: no cover
    app()
