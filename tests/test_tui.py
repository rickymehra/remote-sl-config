"""Pilot tests for the Textual editor (fake MIDI port, no hardware)."""

import asyncio

import pytest
from textual.widgets import Input, Label, Select, Static

from conftest import V_STATION_1, wait_for
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
            warning = str(app.screen.query_one("#confirm-warning", Label).render())
            assert "own risk" in warning
            await pilot.click("#confirm-no")
            await pilot.pause()
            assert port.sent == []
            await pilot.click("#send")
            await pilot.pause()
            await pilot.click("#confirm-yes")
            await wait_for(pilot, lambda: bool(port.sent))
            assert port.sent == [V_STATION_1.read_bytes()]

    run(go())


def test_receive_via_loopback_and_save(tmp_path):
    async def go():
        app = SLConfigApp()  # fake loopback port
        async with app.run_test(size=(200, 60)) as pilot:
            assert isinstance(app.port, midi_io.FakeMidiPort)
            app.port.inbox.append(V_STATION_1.read_bytes())
            await pilot.click("#receive")
            await wait_for(pilot, lambda: app.template.name.startswith("V-Station-1"))
            assert app.template.name.startswith("V-Station-1")
            app.query_one("#path", Input).value = str(tmp_path / "out")
            await pilot.click("#save-syx")
            await pilot.click("#save-json")
            await pilot.pause()
        assert (tmp_path / "out.syx").read_bytes() == V_STATION_1.read_bytes()
        assert codec.encode(app.template) == V_STATION_1.read_bytes()
        assert (tmp_path / "out.json").exists()

    run(go())


def test_panel_geometry_matches_hardware():
    """Controls sit where they are on the SL (player's view, rear at the top)."""

    async def go():
        app = SLConfigApp(path=V_STATION_1)
        async with app.run_test(size=(200, 60)):
            r = {
                s: app.query_one(f"#ctl-{s}").region
                for s in (
                    "button_row1_1",
                    "encoder_1",
                    "button_row2_1",
                    "pot_1",
                    "drum_pad_1",
                    "slider_1",
                    "button_row3_1",
                    "button_row4_1",
                    "rewind",
                    "record",
                    "loop",
                    "mod",
                    "pitch",
                    "touchpad_x1",
                    "touchpad_y2",
                    "expression",
                    "sustain",
                    "encoder_8",
                    "slider_8",
                )
            }
            keys = app.query_one("#keys").region

            def above(a, b):
                return r[a].y < r[b].y

            # left half, rear to front
            assert above("button_row1_1", "encoder_1")
            assert above("encoder_1", "button_row2_1")
            assert above("button_row2_1", "pot_1")
            assert above("pot_1", "drum_pad_1")
            # right half: sliders (two rows deep) at the rear, then rows 3 and 4, transport
            assert r["slider_1"].height == 2 * r["encoder_1"].height
            assert r["slider_1"].y == r["button_row1_1"].y
            assert r["button_row3_1"].y == r["button_row2_1"].y
            assert r["button_row4_1"].y == r["pot_1"].y
            assert r["rewind"].y == r["drum_pad_1"].y
            # columns run left to right; right half is right of the left half
            assert r["encoder_1"].x < r["encoder_8"].x < r["slider_1"].x < r["slider_8"].x
            # transport as printed: ... loop, record
            assert r["rewind"].x < r["loop"].x < r["record"].x
            # joystick and touchpad at the far left; touchpad beside the keys
            assert r["mod"].x < r["encoder_1"].x and above("mod", "touchpad_x1")
            assert r["touchpad_y2"].right <= keys.x and r["touchpad_x1"].y >= keys.y
            assert keys.y > r["drum_pad_1"].y
            # pedals are on the rear strip
            assert above("expression", "button_row1_1") and above("sustain", "button_row1_1")

    run(go())


def test_lcds_and_leds_follow_selection():
    from slcfg.tui.decor import Lcd, Led

    async def go():
        app = SLConfigApp(path=V_STATION_1)
        async with app.run_test(size=(200, 60)) as pilot:
            left, right = app.query_one("#lcd-left", Lcd), app.query_one("#lcd-right", Lcd)
            assert "Osc1Levl" in left.lines[0] and "ENCODERS" in left.lines[2]
            assert app.query_one("#led-encoder", Led).lit
            await pilot.click("#ctl-pot_2")
            await pilot.pause()
            assert left.lines[0].startswith("Portamnt Osc1Fine")
            assert "+0" in left.lines[1]  # Osc1Fine is bipolar: stored 64 shows as +0
            assert app.query_one("#led-pot", Led).lit
            assert not app.query_one("#led-encoder", Led).lit
            await pilot.click("#ctl-button_row3_1")
            await pilot.pause()
            assert right.lines[0].startswith("ArpOnOff")
            assert app.query_one("#led-button_row3", Led).lit
            assert not app.query_one("#led-slider", Led).lit

    run(go())


@pytest.mark.animated
def test_decor_animates_and_can_be_disabled():
    from slcfg.tui.decor import DotField
    from slcfg.tui.panel import FrontPanel

    async def go():
        app = SLConfigApp(path=V_STATION_1)
        async with app.run_test(size=(200, 60)):
            assert app.query_one(FrontPanel).animating
            spiral = app.query_one("#far-right", DotField)

            def frame(t):
                spiral.tick(t)
                lines = [spiral.render_line(y) for y in range(spiral.size.height)]
                text = [line.text for line in lines]
                colors = [seg.style.color for line in lines for seg in line if seg.text.strip()]
                return text, colors

            (text0, colors0), (text1, colors1) = frame(0.0), frame(1.0)
            assert text0 == text1 and any(c.strip() for c in text0)  # same dots...
            assert colors0 != colors1  # ...different glow

        still = SLConfigApp(path=V_STATION_1)
        still.animation_level = "none"
        async with still.run_test(size=(200, 60)):
            assert not still.query_one(FrontPanel).animating

    run(go())


class SilentPort:
    """Behaves like hardware that never answers: receive() waits instead of returning at once."""

    name = "Silent SL"

    def send(self, message):
        pass

    def close(self):
        pass

    def receive(self, timeout):
        import time

        time.sleep(min(timeout, 0.05))
        return None


def test_receive_runs_in_background_and_can_be_cancelled():
    async def go():
        app = SLConfigApp(path=V_STATION_1, port=SilentPort())
        async with app.run_test(size=(200, 60)) as pilot:
            await pilot.click("#receive")
            await pilot.pause(0.2)
            # still listening, but the UI responds: select another control meanwhile
            assert str(app.query_one("#receive").label) == "Cancel"
            await pilot.click("#ctl-pot_1")
            assert app.selected == "pot_1"
            await pilot.click("#receive")  # Cancel
            await wait_for(
                pilot, lambda: "cancelled" in str(app.query_one("#status", Static).render())
            )
            assert "cancelled" in str(app.query_one("#status", Static).render())
            assert str(app.query_one("#receive").label) == "Receive"
            assert app.template.name.startswith("V-Station-1")  # untouched

    run(go())


def test_edit_template_routing():
    async def go():
        app = SLConfigApp(path=V_STATION_1)
        async with app.run_test(size=(200, 60)) as pilot:
            assert app.query_one("#t-common_channel", Select).value == app.template.common_channel
            app.query_one("#t-keyboard_channel", Select).value = 9
            app.query_one("#t-common_port", Select).value = 0x48
            await pilot.click("#apply")
            await pilot.pause()
            assert (app.template.keyboard_channel, app.template.common_port) == (9, 0x48)
            diff = str(app.query_one("#diff", Static).render())
            assert "99" in diff and "102" in diff
            hexview = str(app.query_one("#hex", Static).render())
            assert "routing:" in hexview

    run(go())


def test_unknown_routing_code_is_kept():
    async def go():
        t = codec.decode(V_STATION_1.read_bytes())
        t.keyboard_port = 0x07  # bit 6 clear: meaning unconfirmed, must survive load + apply
        app = SLConfigApp(path=V_STATION_1)
        async with app.run_test(size=(200, 60)) as pilot:
            app.template = t
            app.refresh_all()
            await pilot.click("#apply")
            await pilot.pause()
            assert app.template.keyboard_port == 0x07

    run(go())
