import json

from typer.testing import CliRunner

from conftest import BULK, V_STATION_1
from slcfg.cli import app

runner = CliRunner()


def test_inspect_template():
    r = runner.invoke(app, ["inspect", str(V_STATION_1)])
    assert r.exit_code == 0, r.output
    assert "00 20 29 (Novation)" in r.output
    assert "slot 1, single" in r.output
    assert "label gap 41, record base 419" in r.output
    assert "'Osc1Levl'" in r.output


def test_stride(fixtures):
    r = runner.invoke(app, ["stride", str(fixtures / "stride24_a.syx"), "--top", "1"])
    assert r.exit_code == 0 and "stride   24" in r.output


def test_diff_views(fixtures):
    a, b = fixtures / "stride24_a.syx", fixtures / "stride24_b.syx"
    r = runner.invoke(app, ["diff", str(a), str(b), "--view", "all"])
    assert r.exit_code == 0, r.output
    assert "== view: raw" in r.output and "== view: nibble" in r.output
    assert "1 differing byte(s)" in r.output


def test_diff_annotates_sl_records(tmp_path):
    from slcfg import codec

    t = codec.decode(V_STATION_1.read_bytes())
    t.controls["pot_1"].number = 7
    other = tmp_path / "b.syx"
    other.write_bytes(codec.encode(t))
    r = runner.invoke(app, ["diff", str(V_STATION_1), str(other)])
    assert "r08+17" in r.output


def test_decode_encode_roundtrip(tmp_path):
    js, syx = tmp_path / "t.json", tmp_path / "t.syx"
    assert runner.invoke(app, ["decode", str(V_STATION_1), "-o", str(js)]).exit_code == 0
    doc = json.loads(js.read_text())
    assert doc["controls"]["encoder_1"]["name"] == "Osc1Levl"
    assert runner.invoke(app, ["encode", str(js), "-o", str(syx)]).exit_code == 0
    assert syx.read_bytes() == V_STATION_1.read_bytes()


def test_bulk_roundtrip(tmp_path):
    js, syx = tmp_path / "b.json", tmp_path / "b.syx"
    runner.invoke(app, ["decode", str(BULK), "-o", str(js)])
    assert len(json.loads(js.read_text())["templates"]) == 40
    runner.invoke(app, ["encode", str(js), "-o", str(syx)])
    assert syx.read_bytes() == BULK.read_bytes()


def test_encode_rejects_invalid(tmp_path):
    js = tmp_path / "bad.json"
    js.write_text(json.dumps({"name": "x", "controls": {"encoder_1": {"name": "waytoolongname"}}}))
    r = runner.invoke(app, ["encode", str(js), "-o", str(tmp_path / "o.syx")])
    assert r.exit_code != 0
    assert not (tmp_path / "o.syx").exists()


def test_send_needs_confirmation():
    r = runner.invoke(app, ["send", str(V_STATION_1)], input="n\n")
    assert r.exit_code == 1 and "cancelled" in r.output
    r = runner.invoke(app, ["send", str(V_STATION_1)], input="y\n")
    assert r.exit_code == 0 and "sent 1 message" in r.output
    assert "fake port" in r.output


def test_receive_from_empty_fake(tmp_path):
    r = runner.invoke(app, ["receive", "-o", str(tmp_path / "x.syx"), "--timeout", "0.1"])
    assert r.exit_code == 1 and "nothing received" in r.output


def test_library_opens_tui_on_library(monkeypatch, tmp_path):
    from slcfg.tui.app import SLConfigApp

    seen = []
    monkeypatch.setattr(SLConfigApp, "run", lambda self: seen.append(self))
    r = runner.invoke(app, ["library", str(BULK)])
    assert r.exit_code == 0, r.output
    (tui,) = seen
    assert tui.open_library and len(tui.library.filled()) == 40
    r = runner.invoke(app, ["library", str(tmp_path / "missing.syx")])
    assert r.exit_code != 0 and len(seen) == 1


def test_bulk_send_shows_progress():
    r = runner.invoke(app, ["send", str(BULK)], input="y\n")
    assert r.exit_code == 0, r.output
    assert "sent 40/40" in r.output and "█" * 30 in r.output
