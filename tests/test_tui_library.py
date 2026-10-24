"""Pilot tests for the library screen (fake MIDI port, no hardware)."""

import asyncio

from textual.widgets import DataTable, Input, Static

from conftest import BULK, V_STATION_1, wait_for
from slcfg import codec, midi_io
from slcfg.library import Library
from slcfg.sysex import split_messages
from slcfg.tui.app import ConfirmSend, SLConfigApp
from slcfg.tui.library import LibraryScreen

SIZE = (200, 60)


def run(coro):
    return asyncio.run(coro)


def factory_app(port=None) -> SLConfigApp:
    return SLConfigApp(port=port, library=Library.load(BULK), open_library=True)


def cell(app: SLConfigApp, slot: int, col: int) -> str:
    return str(app.screen.query_one(DataTable).get_row_at(slot - 1)[col])


def status(app: SLConfigApp) -> str:
    return str(app.screen.query_one("#lib-status", Static).render())


def test_open_slot_in_editor_and_apply_updates_library():
    async def go():
        app = factory_app()
        async with app.run_test(size=SIZE) as pilot:
            assert isinstance(app.screen, LibraryScreen)
            assert cell(app, 1, 1) == "V-Station-1 Novation"
            assert cell(app, 1, 4) == ""  # same as factory
            app.screen.query_one(DataTable).move_cursor(row=2)
            await pilot.click("#lib-open")
            await pilot.pause()
            assert not isinstance(app.screen, LibraryScreen)
            assert app.library_slot == 3
            assert app.template.name.startswith("V-Station-3")
            assert app.query_one("#tmpl-slot", Input).value == "3"
            app.query_one("#tmpl-name", Input).value = "My synth"
            await pilot.click("#apply")
            await pilot.pause()
            assert app.library.get(3).name == "My synth"
            assert "library slot 3 updated" in str(app.query_one("#status", Static).render())
            await pilot.press("l")
            await pilot.pause()
            assert isinstance(app.screen, LibraryScreen)
            assert cell(app, 3, 1) == "My synth" and cell(app, 3, 4) == "changed"

    run(go())


def test_open_empty_slot_starts_blank_template():
    async def go():
        app = SLConfigApp(open_library=True)
        async with app.run_test(size=SIZE) as pilot:
            assert cell(app, 5, 1) == "(empty)"
            app.screen.query_one(DataTable).move_cursor(row=4)
            await pilot.press("e")
            await pilot.pause()
            assert app.template.slot == 5 and app.library_slot == 5
            await pilot.click("#apply")
            await pilot.pause()
            assert app.library.get(5).name == "New template"

    run(go())


def test_swap_with_neighbour():
    async def go():
        app = factory_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.click("#lib-down")
            await pilot.pause()
            assert cell(app, 1, 1) == "V-Station-2 Novation"
            assert cell(app, 2, 1) == "V-Station-1 Novation"
            assert app.screen.query_one(DataTable).cursor_row == 1
            assert cell(app, 1, 4) == "changed"
            data = app.library.to_bytes()
            assert data[codec.SLOT_OFFSET] == 0 and data[codec.MESSAGE_LEN + 12] == 1
            await pilot.press("shift+up")
            await pilot.pause()
            assert app.library.to_bytes() == BULK.read_bytes()
            await pilot.click("#lib-up")  # already at the top: no-op
            await pilot.pause()
            assert app.library.to_bytes() == BULK.read_bytes()

    run(go())


def test_send_all_requires_confirm():
    async def go():
        port = midi_io.FakeMidiPort()
        app = factory_app(port)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.click("#lib-send-all")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmSend)
            await pilot.click("#confirm-no")
            await pilot.pause()
            assert port.sent == []
            assert "cancelled" in status(app)
            await pilot.click("#lib-send-all")
            await pilot.pause()
            assert port.sent == []  # nothing before "Send"
            await pilot.click("#confirm-yes")
            await wait_for(pilot, lambda: "sent 40" in status(app))
            assert len(port.sent) == 40
            assert b"".join(port.sent) == BULK.read_bytes()
            assert "sent 40" in status(app)

    run(go())


def test_send_slot_requires_confirm():
    async def go():
        port = midi_io.FakeMidiPort()
        app = factory_app(port)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.click("#lib-send-slot")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmSend)
            await pilot.click("#confirm-yes")
            await wait_for(pilot, lambda: bool(port.sent))
            assert port.sent == [split_messages(BULK.read_bytes())[0].data]

    run(go())


def test_receive_all_fills_table():
    async def go():
        msgs = [m.data for m in split_messages(BULK.read_bytes())]
        port = midi_io.FakeMidiPort(inbox=[*msgs, b"\xf0\x7e\x00\xf7"])
        app = SLConfigApp(port=port, open_library=True)
        async with app.run_test(size=SIZE) as pilot:
            assert cell(app, 40, 1) == "(empty)"
            await pilot.click("#lib-receive")
            await wait_for(pilot, lambda: "received 40" in status(app))
            assert cell(app, 40, 1).startswith("Ableton Live Automap")
            assert all(cell(app, s, 4) == "" for s in range(1, 41))
            assert app.library.to_bytes() == BULK.read_bytes()
            assert "received 40" in status(app)
            await pilot.click("#lib-receive")  # inbox now empty except the junk message
            await wait_for(pilot, lambda: "skipped 1" in status(app))
            assert "skipped 1" in status(app)
            await pilot.click("#lib-receive")
            await wait_for(pilot, lambda: "nothing received" in status(app))
            assert "nothing received" in status(app)

    run(go())


def test_import_export_save_load(tmp_path):
    async def go():
        app = factory_app()
        async with app.run_test(size=SIZE) as pilot:
            path = app.screen.query_one("#lib-path", Input)
            table = app.screen.query_one(DataTable)
            await pilot.click("#lib-save")
            await pilot.pause()
            assert "enter a path" in status(app)
            table.move_cursor(row=39)
            path.value = str(V_STATION_1)
            await pilot.click("#lib-import")
            await pilot.pause()
            assert cell(app, 40, 1) == "V-Station-1 Novation" and cell(app, 40, 4) == "changed"
            path.value = str(tmp_path / "slot40.json")
            await pilot.click("#lib-export")
            path.value = str(tmp_path / "lib")
            await pilot.click("#lib-save")
            await pilot.pause()
            assert (tmp_path / "slot40.json").exists()
            assert Library.load(tmp_path / "lib.syx").get(40).name.startswith("V-Station-1")
            await pilot.click("#lib-clear")
            await pilot.pause()
            assert cell(app, 40, 1) == "(empty)"
            path.value = str(BULK)
            await pilot.click("#lib-load")
            await pilot.pause()
            assert cell(app, 40, 1).startswith("Ableton") and "loaded 40" in status(app)
            path.value = str(tmp_path / "missing.syx")
            await pilot.click("#lib-load")
            await pilot.pause()
            assert "load failed" in status(app)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, LibraryScreen)

    run(go())


def test_send_all_shows_progress_bar():
    from textual.widgets import ProgressBar

    async def go():
        port = midi_io.FakeMidiPort()
        app = factory_app(port)
        async with app.run_test(size=SIZE) as pilot:
            bar = app.screen.query_one("#lib-progress", ProgressBar)
            assert not bar.display or "active" not in bar.classes
            seen = []
            orig = bar.update

            def spy(**kw):
                seen.append(kw.get("progress"))
                return orig(**kw)

            bar.update = spy
            await pilot.click("#lib-send-all")
            await pilot.pause()
            await pilot.click("#confirm-yes")
            await wait_for(pilot, lambda: "sent 40" in status(app))
            assert seen[0] == 0 and seen[-1] == 40  # shown at 0, filled to 40
            assert "active" not in bar.classes  # hidden again when done
            assert len(port.sent) == 40

    run(go())
