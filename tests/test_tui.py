"""Pilot tests for the Textual editor (fake MIDI port, no hardware)."""

import asyncio

from textual.widgets import Input, Static

from conftest import V_STATION_1
from slcfg import codec, midi_io
from slcfg.tui.app import ConfirmSend, SLConfigApp


def run(coro):
    return asyncio.run(coro)


def test_edit_control_and_diff():
    async def go():
        app = SLConfigApp(path=V_STATION_1)
        async with app.run_test(size=(200, 60)) as pilot:
            await pilot.click("#ctl-pot_1")
            assert app.selected == "pot_1"
            assert app.query_one("#f-name", Input).value == "Portamnt"
            app.query_one("#f-name", Input).value = "Glide"
            app.query_one("#f-number", Input).value = "65"
            await pilot.click("#apply")
            await pilot.pause()
            c = app.template.controls["pot_1"]
            assert (c.name, c.number) == ("Glide", 65)
            diff = str(app.query_one("#diff", Static).render())
            assert "r08+17" in diff
            assert "Glide" in str(app.query_one("#ctl-pot_1").label)

    run(go())


def test_validation_rejects_bad_input():
    async def go():
        app = SLConfigApp(path=V_STATION_1)
        async with app.run_test(size=(200, 60)) as pilot:
            await pilot.click("#ctl-encoder_1")
            app.query_one("#f-high", Input).value = "300"
            await pilot.click("#apply")
            await pilot.pause()
            assert "invalid" in str(app.query_one("#status", Static).render())
            assert app.template.controls["encoder_1"].high == 127

    run(go())


def test_send_requires_confirm_dialog():
    async def go():
        port = midi_io.FakeMidiPort()
        app = SLConfigApp(path=V_STATION_1, port=port)
        async with app.run_test(size=(200, 60)) as pilot:
            await pilot.click("#send")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmSend)
            await pilot.click("#confirm-no")
            await pilot.pause()
            assert port.sent == []
            await pilot.click("#send")
            await pilot.pause()
            await pilot.click("#confirm-yes")
            await pilot.pause()
            assert port.sent == [V_STATION_1.read_bytes()]

    run(go())


def test_receive_via_loopback_and_save(tmp_path):
    async def go():
        app = SLConfigApp()  # fake loopback port
        async with app.run_test(size=(200, 60)) as pilot:
            assert isinstance(app.port, midi_io.FakeMidiPort)
            app.port.inbox.append(V_STATION_1.read_bytes())
            await pilot.click("#receive")
            await pilot.pause()
            assert app.template.name.startswith("V-Station-1")
            app.query_one("#path", Input).value = str(tmp_path / "out")
            await pilot.click("#save-syx")
            await pilot.click("#save-json")
            await pilot.pause()
        assert (tmp_path / "out.syx").read_bytes() == V_STATION_1.read_bytes()
        assert codec.encode(app.template) == V_STATION_1.read_bytes()
        assert (tmp_path / "out.json").exists()

    run(go())
