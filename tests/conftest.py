from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
COMMUNITY = sorted((ROOT / "dumps" / "community").rglob("*.syx"))
V_STATION_1 = ROOT / "dumps/community/novation-factory-os41/01_-_Novation_-_V-Station-1.syx"
BULK = ROOT / "dumps/community/novation-factory-os41/bulk/SL_Factory_Templates_OS41.syx"


@pytest.fixture
def vstation() -> bytes:
    return V_STATION_1.read_bytes()


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES
