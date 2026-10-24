"""Textual editor for ReMOTE SL templates.

The panel (``panel.py``) is laid out like the hardware; selecting a control opens it in the
form below. All
hardware access goes through :mod:`slcfg.midi_io`; without ``--device`` a loopback fake port
is used, and every send needs a confirmation dialog.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, ScrollableContainer, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from .. import codec, midi_io
from ..diff import diff_bytes, format_diff
from ..model import (
    BUTTON_MODES,
    CONTROL_TYPES,
    NAME_LEN,
    SLOT_BY_KEY,
    SLOTS,
    Control,
    Template,
    ValidationError,
    check_name,
    check_range,
)
from .panel import FrontPanel, empty_label

INT_FIELDS = [
    # (field, label, max)
    ("number", "CC / NRPN lsb", 127),
    ("number_msb", "NRPN msb", 127),
    ("low", "Low value", 127),
    ("high", "High value", 127),
    ("value", "Stored value", 127),
    ("step", "Step", 127),
    ("display", "Display code", 127),
    ("channel", "Channel code", 127),
    ("port", "Port code", 127),
]


def blank_template() -> Template:
    return codec.decode(codec.encode(Template(name="New template")))


class ConfirmSend(ModalScreen[bool]):
    """Explicit yes/no before anything is transmitted."""

    DEFAULT_CSS = """
    ConfirmSend { align: center middle; }
    #dialog { width: 80; height: auto; border: thick $warning; padding: 1 2; background: $surface; }
    #dialog Horizontal { height: auto; margin-top: 1; }
    #dialog Label { width: 100%; }
    #confirm-warning { color: $warning; margin: 1 0; }
    """

    def __init__(self, summary: str) -> None:
        super().__init__()
        self.summary = summary

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.summary, id="confirm-summary")
            yield Label(midi_io.HARDWARE_WARNING, id="confirm-warning")
            yield Label("This overwrites the SL's edit buffer. Continue?")
            with Horizontal():
                yield Button("Send", variant="error", id="confirm-yes")
                yield Button("Cancel", variant="primary", id="confirm-no")

    @on(Button.Pressed, "#confirm-yes")
    def yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#confirm-no")
    def no(self) -> None:
        self.dismiss(False)


class SLConfigApp(App[None]):
    TITLE = "slcfg - ReMOTE SL template editor"
    CSS = """
    #top, #tmpl, #actions { height: 3; }
    #top Input, #tmpl-name { width: 1fr; }
    #tmpl-slot { width: 14; }
    #top Button, #actions Button { min-width: 8; margin-right: 1; }
    #panel-scroll { height: auto; max-height: 60%; }
    #status { height: 1; color: $warning; }
    #bottom { height: 1fr; min-height: 12; }
    #editor { width: 1fr; padding: 0 1; border-top: solid $primary; }
    #side-title { height: 1; margin-left: 2; content-align: left middle; }
    #fields { grid-size: 6; grid-gutter: 0 1; height: auto; }
    .field { height: 4; }
    .field-label { height: 1; color: $text-muted; }
    #fields Input, #fields Select { width: 100%; }
    #previews { width: 1fr; border-top: solid $primary; }
    """
    BINDINGS = [
        Binding("ctrl+s", "save_json", "Save JSON"),
        Binding("ctrl+e", "save_syx", "Save .syx"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        path: Path | None = None,
        device: str | None = None,
        port: midi_io.MidiPort | None = None,
    ) -> None:
        super().__init__()
        self.path = path
        self.device = device
        if port is None:
            port = midi_io.open_port(device)
            if isinstance(port, midi_io.FakeMidiPort):
                port.echo = True  # loopback so "Receive" can be exercised without hardware
        self.port = port
        self.template: Template = blank_template()
        self.loaded_bytes: bytes = codec.encode(self.template)
        self.selected: str = "encoder_1"

    # ---- layout -----------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top"):
            yield Input(str(self.path or ""), placeholder="path to .syx or .json", id="path")
            yield Button("Load", id="load")
            yield Button("Save JSON", id="save-json")
            yield Button("Save .syx", id="save-syx")
            yield Button("Send to device", variant="warning", id="send")
            yield Button("Receive", id="receive")
        with Horizontal(id="tmpl"):
            yield Input(placeholder="template name (48)", id="tmpl-name", max_length=48)
            yield Input(placeholder="slot 1-40", id="tmpl-slot", max_length=2)
        with ScrollableContainer(id="panel-scroll"):
            yield FrontPanel(id="panel")
        yield Static("", id="status")
        with Horizontal(id="bottom"):
            with VerticalScroll(id="editor"):
                with Horizontal(id="actions"):
                    yield Button("Apply", variant="primary", id="apply")
                    yield Button("Revert", id="revert")
                    yield Label("", id="side-title")
                with Grid(id="fields"):
                    with Vertical(classes="field"):
                        yield Label("Name (max 8)", classes="field-label")
                        yield Input(id="f-name", max_length=NAME_LEN)
                    with Vertical(classes="field"):
                        yield Label("Type", classes="field-label")
                        yield Select(
                            [(v, v) for v in CONTROL_TYPES.values()], id="f-type", allow_blank=False
                        )
                    with Vertical(classes="field"):
                        yield Label("Button mode", classes="field-label")
                        yield Select(
                            [(v, v) for v in BUTTON_MODES.values()],
                            id="f-button_mode",
                            allow_blank=False,
                        )
                    for name, label, _ in INT_FIELDS:
                        with Vertical(classes="field"):
                            yield Label(label, classes="field-label")
                            yield Input(id=f"f-{name}", restrict=r"[0-9]*", max_length=5)
            with TabbedContent(id="previews"):
                with TabPane("Hex preview", id="tab-hex"):
                    yield Static("", id="hex")
                with TabPane("Diff vs loaded", id="tab-diff"):
                    yield Static("", id="diff")
        yield Footer()

    def on_mount(self) -> None:
        if self.path:
            self.load(self.path)
        else:
            self.refresh_all()

    # ---- state <-> widgets ------------------------------------------------------------------

    def load(self, path: Path) -> None:
        from ..cli import load_templates

        try:
            ts = load_templates(path)
        except (OSError, ValueError, KeyError) as e:
            self.set_status(f"load failed: {e}")
            return
        self.template = ts[0]
        self.loaded_bytes = codec.encode(self.template)
        self.path = path
        note = f" (first of {len(ts)})" if len(ts) > 1 else ""
        self.set_status(f"loaded {path}{note}")
        self.refresh_all()

    def refresh_all(self) -> None:
        self.query_one("#tmpl-name", Input).value = self.template.name
        self.query_one("#tmpl-slot", Input).value = str(self.template.slot)
        for s in SLOTS:
            c = self.template.controls.get(s.key)
            btn = self.query_one(f"#ctl-{s.key}", Button)
            btn.label = (c.name.strip() if c and c.name.strip() else empty_label(s.key))[:8]
        self.select(self.selected)

    def select(self, key: str) -> None:
        self.selected = key
        self.query_one(FrontPanel).show(self.template, key)
        c = self.template.control(key)
        s = SLOT_BY_KEY[key]
        self.query_one("#side-title", Label).update(f"{s.label}  [record {s.index + 1}]")
        self.query_one("#f-name", Input).value = c.name
        self.query_one("#f-type", Select).value = (
            c.type if c.type in CONTROL_TYPES.values() else "none"
        )
        self.query_one("#f-button_mode", Select).value = c.button_mode
        for name, _, _ in INT_FIELDS:
            self.query_one(f"#f-{name}", Input).value = str(getattr(c, name))
        self.refresh_previews()

    def form_to_control(self) -> Control:
        """Validate the side form and return an updated copy of the selected control."""
        c = copy.deepcopy(self.template.control(self.selected))
        name = self.query_one("#f-name", Input).value
        check_name(name)
        c.name = name
        c.type = str(self.query_one("#f-type", Select).value)
        c.button_mode = str(self.query_one("#f-button_mode", Select).value)
        for field, label, hi in INT_FIELDS:
            text = self.query_one(f"#f-{field}", Input).value.strip()
            if not text.isdigit():
                raise ValidationError(f"{label}: enter a number 0..{hi}")
            value = int(text)
            # 14-bit values from a dump are shown as-is; new input is limited to 0..127
            if value != getattr(c, field):
                check_range(label, value, 0, hi)
            setattr(c, field, value)
        c.validate()
        return c

    def refresh_previews(self) -> None:
        try:
            data = codec.encode(self.template)
        except (ValidationError, codec.CodecError) as e:
            self.query_one("#hex", Static).update(f"cannot encode: {e}")
            return
        s = SLOT_BY_KEY[self.selected]
        off = codec.RECORD_BASE + s.index * codec.RECORD_LEN
        rec = data[off : off + codec.RECORD_LEN]
        hex_lines = [
            f"template: {len(data)} bytes, header {data[:13].hex(' ')}",
            f"record {s.index + 1} @ {off} (0x{off:04X}):",
            "  +00 " + rec[:16].hex(" "),
            "  +16 " + rec[16:32].hex(" "),
            "  +32 " + rec[32:].hex(" "),
        ]
        self.query_one("#hex", Static).update("\n".join(hex_lines))
        diffs = diff_bytes(self.loaded_bytes, data)
        self.query_one("#diff", Static).update(
            format_diff(diffs, record_base=codec.RECORD_BASE, stride=codec.RECORD_LEN)
            if diffs
            else "no changes vs loaded file"
        )

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    # ---- events -----------------------------------------------------------------------------

    @on(Button.Pressed, ".ctl")
    def ctl_pressed(self, event: Button.Pressed) -> None:
        assert event.button.id
        self.select(event.button.id.removeprefix("ctl-"))

    @on(Button.Pressed, "#apply")
    def apply(self) -> None:
        try:
            c = self.form_to_control()
            name = self.query_one("#tmpl-name", Input).value
            check_name(name, 48)
            slot_text = self.query_one("#tmpl-slot", Input).value.strip()
            if not slot_text.isdigit():
                raise ValidationError("slot must be a number 1..40")
            check_range("slot", int(slot_text), 1, 40)
        except ValidationError as e:
            self.set_status(f"invalid: {e}")
            return
        self.template.controls[self.selected] = c
        self.template.name = name
        self.template.slot = int(slot_text)
        self.set_status(f"updated {self.selected}")
        self.refresh_all()

    @on(Button.Pressed, "#revert")
    def revert(self) -> None:
        self.select(self.selected)
        self.set_status("form reverted")

    @on(Button.Pressed, "#load")
    def load_pressed(self) -> None:
        text = self.query_one("#path", Input).value.strip()
        if text:
            self.load(Path(text))

    @on(Button.Pressed, "#save-json")
    def action_save_json(self) -> None:
        path = self._target(".json")
        if path:
            path.write_text(json.dumps(self.template.to_json(), indent=2) + "\n")
            self.set_status(f"saved {path}")

    @on(Button.Pressed, "#save-syx")
    def action_save_syx(self) -> None:
        path = self._target(".syx")
        if path:
            path.write_bytes(codec.encode(self.template))
            self.set_status(f"saved {path}")

    def _target(self, suffix: str) -> Path | None:
        text = self.query_one("#path", Input).value.strip()
        if not text:
            self.set_status("enter a path first")
            return None
        return Path(text).with_suffix(suffix)

    @on(Button.Pressed, "#send")
    def send_pressed(self) -> None:
        try:
            data = codec.encode(self.template)
        except (ValidationError, codec.CodecError) as e:
            self.set_status(f"cannot send: {e}")
            return
        name = " ".join(self.template.name.split())
        summary = f"Send '{name}' ({midi_io.describe(data)}) to {self.port.name!r}"

        def done(ok: bool | None) -> None:
            if not ok:
                self.set_status("send cancelled, nothing sent")
                return
            try:
                n = midi_io.send_template(self.port, data, lambda _s: True)
            except midi_io.MidiIOError as e:
                self.set_status(f"send failed: {e}")
                return
            self.set_status(f"sent {n} message(s) to {self.port.name}")

        self.push_screen(ConfirmSend(summary), done)

    @on(Button.Pressed, "#receive")
    def receive_pressed(self) -> None:
        msgs = midi_io.receive_dump(self.port, timeout=5.0, count=1)
        if not msgs:
            self.set_status("nothing received (dump a template from the SL, then retry)")
            return
        try:
            self.template = codec.decode(msgs[0])
        except codec.CodecError as e:
            self.set_status(f"received data is not a template: {e}")
            return
        self.loaded_bytes = msgs[0]
        self.set_status(f"received template '{self.template.name}'")
        self.refresh_all()
