"""Library screen: the SL's 40 template memories in one table.

Pick a slot to open it in the editor, reorder, import/export single templates, save the
whole set as a bulk .syx, and receive/send it from/to the device. Every send goes through
:class:`~slcfg.tui.app.ConfirmSend` and :func:`slcfg.midi_io.send_template`. The library
itself lives on the app (``app.library``) so editor and screen share it.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, ProgressBar, Static

from .. import codec, midi_io
from ..library import Library, LibraryError
from ..model import NUM_SLOTS, ValidationError
from .app import ConfirmSend

if TYPE_CHECKING:
    from .app import SLConfigApp

COLUMNS = ("Slot", "Name", "Controls", "Group", "vs factory")


class LibraryScreen(Screen[None]):
    DEFAULT_CSS = """
    LibraryScreen { background: #101010; }
    LibraryScreen #lib-top, LibraryScreen #lib-actions { height: 3; }
    LibraryScreen #lib-path { width: 1fr; }
    LibraryScreen Button { min-width: 8; margin-right: 1; }
    LibraryScreen #lib-table { height: 1fr; border: round #39ff14; background: #101010; }
    LibraryScreen #lib-table > .datatable--header { color: #39ff14; background: #1b1b1b; }
    LibraryScreen #lib-table > .datatable--cursor { background: #39ff14; color: #101010; }
    LibraryScreen #lib-status-row { height: 1; }
    LibraryScreen #lib-status { height: 1; width: 1fr; color: $warning; }
    """
    BINDINGS = [
        Binding("e", "open", "Edit slot"),
        Binding("shift+up", "move(-1)", "Move up"),
        Binding("shift+down", "move(1)", "Move down"),
        Binding("escape", "back", "Editor"),
    ]

    @property
    def sl(self) -> SLConfigApp:
        return cast("SLConfigApp", self.app)

    @property
    def library(self) -> Library:
        return self.sl.library

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="lib-top"):
            yield Input(placeholder="path to .syx / .json / folder", id="lib-path")
            yield Button("Load library", id="lib-load")
            yield Button("Save bulk .syx", id="lib-save")
            yield Button("Import to slot", id="lib-import")
            yield Button("Export slot", id="lib-export")
        with Horizontal(id="lib-actions"):
            yield Button("Edit", variant="primary", id="lib-open")
            yield Button("Up", id="lib-up")
            yield Button("Down", id="lib-down")
            yield Button("Clear", id="lib-clear")
            yield Button("Receive all", id="lib-receive")
            yield Button("Send slot", variant="warning", id="lib-send-slot")
            yield Button("Send all", variant="warning", id="lib-send-all")
            yield Button("Back", id="lib-back")
        yield DataTable(id="lib-table", cursor_type="row", zebra_stripes=True)
        with Horizontal(id="lib-status-row"):
            yield Static("", id="lib-status")
            yield ProgressBar(id="lib-progress", show_eta=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns(*COLUMNS)
        self.refresh_table()
        self.query_one(DataTable).focus()

    def on_screen_resume(self) -> None:
        self.refresh_table()  # the editor may have changed a slot

    # ---- helpers ----------------------------------------------------------------------------

    @property
    def cursor_slot(self) -> int:
        return self.query_one(DataTable).cursor_row + 1

    def refresh_table(self, cursor: int | None = None) -> None:
        table = self.query_one(DataTable)
        row = table.cursor_row if cursor is None else cursor - 1
        ref = self.sl.library_reference
        table.clear()
        for slot in range(1, NUM_SLOTS + 1):
            s = self.library.summary(slot, ref)
            group = f"{s.group_position}/{s.group_size}" if s.group_size else "-"
            mark = "?" if s.changed is None else ("changed" if s.changed else "")
            if s.empty:
                table.add_row(str(slot), "(empty)", "", "", mark)
            else:
                table.add_row(str(slot), s.name, str(s.controls), group, mark)
        table.move_cursor(row=max(0, min(row, NUM_SLOTS - 1)))

    def set_status(self, text: str) -> None:
        self.query_one("#lib-status", Static).update(text)

    def _path(self, suffix: str | None = None) -> Path | None:
        text = self.query_one("#lib-path", Input).value.strip()
        if not text:
            self.set_status("enter a path first")
            return None
        path = Path(text)
        if suffix and path.suffix.lower() != suffix:
            path = path.with_suffix(suffix)
        return path

    def _confirm_and_send(self, data: bytes, summary: str) -> None:
        def done(ok: bool | None) -> None:
            if not ok:
                self.set_status("send cancelled, nothing sent")
                return
            self.sl.send_in_background(
                data, self.set_status, self.query_one("#lib-progress", ProgressBar)
            )

        self.app.push_screen(ConfirmSend(summary), done)

    # ---- actions ----------------------------------------------------------------------------

    @on(DataTable.RowSelected)
    @on(Button.Pressed, "#lib-open")
    def action_open(self) -> None:
        self.sl.open_from_library(self.cursor_slot)

    @on(Button.Pressed, "#lib-back")
    def action_back(self) -> None:
        self.app.pop_screen()

    def action_move(self, delta: int) -> None:
        a = self.cursor_slot
        b = a + delta
        if not 1 <= b <= NUM_SLOTS:
            return
        self.library.swap(a, b)
        self.sl.library_moved(a, b)
        self.refresh_table(cursor=b)
        self.set_status(f"swapped slots {a} and {b}")

    @on(Button.Pressed, "#lib-up")
    def up(self) -> None:
        self.action_move(-1)

    @on(Button.Pressed, "#lib-down")
    def down(self) -> None:
        self.action_move(1)

    @on(Button.Pressed, "#lib-clear")
    def clear(self) -> None:
        slot = self.cursor_slot
        self.library.clear(slot)
        self.refresh_table()
        self.set_status(f"cleared slot {slot}")

    @on(Button.Pressed, "#lib-load")
    def load(self) -> None:
        path = self._path()
        if path is None:
            return
        try:
            self.sl.library = Library.load(path)
        except LibraryError as e:
            self.set_status(f"load failed: {e}")
            return
        self.sl.library_slot = None
        self.refresh_table()
        self.set_status(f"loaded {len(self.library.filled())} template(s) from {path}")

    @on(Button.Pressed, "#lib-save")
    def save(self) -> None:
        path = self._path(".syx")
        if path is None:
            return
        try:
            n = self.library.save_bulk(path)
        except (LibraryError, OSError) as e:
            self.set_status(f"save failed: {e}")
            return
        self.set_status(f"saved {n} template(s) to {path}")

    @on(Button.Pressed, "#lib-import")
    def import_(self) -> None:
        path, slot = self._path(), self.cursor_slot
        if path is None:
            return
        try:
            t = self.library.import_file(slot, path)
        except LibraryError as e:
            self.set_status(f"import failed: {e}")
            return
        self.refresh_table()
        self.set_status(f"imported '{' '.join(t.name.split())}' into slot {slot}")

    @on(Button.Pressed, "#lib-export")
    def export(self) -> None:
        path, slot = self._path(), self.cursor_slot
        if path is None:
            return
        if path.suffix.lower() not in (".syx", ".json"):
            path = path.with_suffix(".syx")
        try:
            self.library.export(slot, path)
        except (LibraryError, OSError) as e:
            self.set_status(f"export failed: {e}")
            return
        self.set_status(f"exported slot {slot} to {path}")

    @on(Button.Pressed, "#lib-receive")
    def receive_all(self) -> None:
        self.sl.receive_in_background(
            self.query_one("#lib-receive", Button),
            NUM_SLOTS,
            120.0,
            self._received_all,
            self.set_status,
            self.query_one("#lib-progress", ProgressBar),
        )

    def _received_all(self, msgs: list[bytes]) -> None:
        if not msgs:
            self.set_status("nothing received (on the SL: Global > Template Dump, send all)")
            return
        got, bad = 0, 0
        for msg in msgs:
            try:
                t = codec.decode(msg)
                self.library.put(t.slot, t)
            except (codec.CodecError, LibraryError):
                bad += 1
                continue
            got += 1
        self.refresh_table()
        skipped = f", skipped {bad} non-template message(s)" if bad else ""
        self.set_status(f"received {got} template(s){skipped}")

    @on(Button.Pressed, "#lib-send-slot")
    def send_slot(self) -> None:
        slot = self.cursor_slot
        t = self.library.get(slot)
        if t is None:
            self.set_status(f"slot {slot} is empty, nothing to send")
            return
        try:
            data = codec.encode(t)
        except (ValidationError, codec.CodecError) as e:
            self.set_status(f"cannot send: {e}")
            return
        name = " ".join(t.name.split())
        summary = f"Send slot {slot} '{name}' ({midi_io.describe(data)}) to {self.sl.port.name!r}"
        self._confirm_and_send(data, summary)

    @on(Button.Pressed, "#lib-send-all")
    def send_all(self) -> None:
        if not self.library.filled():
            self.set_status("library is empty, nothing to send")
            return
        try:
            data = self.library.to_bytes()
        except (ValidationError, codec.CodecError) as e:
            self.set_status(f"cannot send: {e}")
            return
        n = len(self.library.filled())
        summary = (
            f"Send all {n} library template(s) ({midi_io.describe(data)}) to {self.sl.port.name!r}"
        )
        self._confirm_and_send(data, summary)
