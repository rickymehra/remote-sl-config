from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
COMMUNITY = sorted((ROOT / "dumps" / "community").rglob("*.syx"))
V_STATION_1 = ROOT / "dumps/community/novation-factory-os41/01_-_Novation_-_V-Station-1.syx"
BULK = ROOT / "dumps/community/novation-factory-os41/bulk/SL_Factory_Templates_OS41.syx"


@pytest.fixture(autouse=True)
def _instant_buttons(monkeypatch):
    """A Textual Button ignores clicks while its ~0.2 s "pressed" highlight is on, so two
    quick pilot clicks on one button could drop the second on a slow CI runner."""
    from textual.widgets import Button

    monkeypatch.setattr(Button, "_start_active_affect", lambda self: None)


@pytest.fixture(autouse=True)
def _no_tui_animation(request, monkeypatch):
    """Textual apps in tests start with animations off (8 fps redraws make pilot tests slow).
    Mark a test ``@pytest.mark.animated`` to keep them on."""
    if request.node.get_closest_marker("animated") is None:
        import textual.constants

        monkeypatch.setattr(textual.constants, "TEXTUAL_ANIMATIONS", "none")


async def wait_for(pilot, condition, timeout: float = 10.0) -> None:
    """Let the app run until ``condition()`` holds; background transfers finish on their
    own schedule, so tests wait for the outcome instead of a fixed number of pauses."""
    import time

    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {condition}")
        await pilot.pause(0.02)
    await pilot.pause()


@pytest.fixture
def vstation() -> bytes:
    return V_STATION_1.read_bytes()


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES
