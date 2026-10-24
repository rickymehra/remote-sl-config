from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
COMMUNITY = sorted((ROOT / "dumps" / "community").rglob("*.syx"))
V_STATION_1 = ROOT / "dumps/community/novation-factory-os41/01_-_Novation_-_V-Station-1.syx"
BULK = ROOT / "dumps/community/novation-factory-os41/bulk/SL_Factory_Templates_OS41.syx"


@pytest.fixture(autouse=True)
def _no_tui_animation(request, monkeypatch):
    """Textual apps in tests start with animations off (8 fps redraws make pilot tests slow).
    Mark a test ``@pytest.mark.animated`` to keep them on."""
    if request.node.get_closest_marker("animated") is None:
        import textual.constants

        monkeypatch.setattr(textual.constants, "TEXTUAL_ANIMATIONS", "none")


@pytest.fixture
def vstation() -> bytes:
    return V_STATION_1.read_bytes()


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES
