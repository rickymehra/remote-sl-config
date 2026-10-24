import asyncio

import pytest
from textual.widgets import Input, Static

from conftest import BULK, V_STATION_1, wait_for
from slcfg import codec
from slcfg.automap import locked_slots, profile
from slcfg.model import SLOTS
from slcfg.tui.app import SLConfigApp

FACTORY = codec.decode_file(BULK.read_bytes())


def by_group(keys):
    groups = {}
    for s in SLOTS:
        if s.key in keys:
            groups.setdefault(s.group, 0)
            groups[s.group] += 1
    return groups


@pytest.mark.parametrize(
    "slot,expected",
    [(34, "protools"), (37, "reason"), (38, "universal"), (39, "logic"), (40, "ableton")],
)
def test_factory_automap_templates_are_recognised(slot, expected):
    assert profile(FACTORY[slot - 1]) == expected


def test_standard_templates_lock_nothing():
    assert all(
        not locked_slots(t) for i, t in enumerate(FACTORY) if i + 1 not in (34, 37, 38, 39, 40)
    )
    assert not locked_slots(codec.decode(V_STATION_1.read_bytes()))


def test_ableton_lock_matches_the_user_guide():
    locked = locked_slots(FACTORY[39])
    groups = by_group(locked)
    # guide §10.2: pots, lower-left button row and pads are free; keys/joystick/pedals too
    for free in ("pot", "button_row2", "drum_pad", "pedal", "joystick"):
        assert free not in groups
    for automap in ("encoder", "button_row1", "slider", "transport"):
        assert automap in groups


def test_keyboard_routed_controls_stay_free():
    universal = locked_slots(FACTORY[37])
    # in Automap Universal the pads follow the keyboard port (code 0x20)
    assert "drum_pad" not in by_group(universal)
    assert "encoder" in by_group(universal)


def test_tui_locks_and_toggles(tmp_path):
    path = tmp_path / "live.syx"
    path.write_bytes(codec.encode(FACTORY[39]))

    async def go():
        app = SLConfigApp(path=path)
        async with app.run_test(size=(200, 60)) as pilot:
            status = lambda: str(app.query_one("#status", Static).render())  # noqa: E731
            assert "ableton Automap template" in status()
            assert "locked" in app.query_one("#ctl-encoder_1").classes
            assert "locked" not in app.query_one("#ctl-pot_1").classes
            # a locked control is read-only and Apply refuses
            await pilot.click("#ctl-encoder_1")
            assert app.query_one("#f-name", Input).disabled
            assert app.query_one("#apply").disabled
            app.query_one("#f-name", Input).value = "Hacked"
            app.apply()  # even if called directly, a locked control is not changed
            assert app.template.controls["encoder_1"].name.strip() == "Encoder1"
            assert "locked" in status()
            # a free control is editable
            await pilot.click("#ctl-pot_1")
            assert not app.query_one("#f-name", Input).disabled
            app.query_one("#f-name", Input).value = "Filter"
            await pilot.click("#apply")
            await wait_for(pilot, lambda: app.template.controls["pot_1"].name == "Filter")
            # toggle off: everything editable
            await pilot.press("escape")  # leave the input so "a" reaches the app
            app.set_focus(None)
            await pilot.press("a")
            await pilot.pause()
            assert not app.automap_lock and "locked" not in app.query_one("#ctl-encoder_1").classes
            assert "Automap lock OFF" in status()
            await pilot.click("#ctl-encoder_1")
            assert not app.query_one("#apply").disabled
            await pilot.press("a")
            await pilot.pause()
            assert app.automap_lock and "locked" in app.query_one("#ctl-encoder_1").classes

    asyncio.run(go())


def test_toggle_on_standard_template_explains():
    async def go():
        app = SLConfigApp(path=V_STATION_1)
        async with app.run_test(size=(200, 60)) as pilot:
            app.set_focus(None)
            await pilot.press("a")
            await pilot.pause()
            assert "not an Automap template" in str(app.query_one("#status", Static).render())

    asyncio.run(go())
