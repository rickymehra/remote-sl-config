import re

import pytest
from typer.testing import CliRunner

from conftest import ROOT
from slcfg import codec, midi_io
from slcfg.capture import (
    Ctx,
    Session,
    Wizard,
    build_steps,
    check_c4,
    check_names,
    code_to_slot,
    describe_changes,
    format_changes,
    slot_to_code,
)
from slcfg.cli import app
from slcfg.model import SLOTS
from slcfg.simulate import SimulatedSL

USER2 = ROOT / "dumps/community/novation-factory-os41/36_-_-_User2.syx"


class ScriptedUI:
    """Answers prompts from a list; confirms sends when ``confirm`` is True."""

    def __init__(self, answers=(), confirm=True):
        self.answers = list(answers)
        self.confirm_answer = confirm
        self.out: list[str] = []

    def say(self, text=""):
        self.out.append(text)

    def ask(self, prompt, default=""):
        self.out.append(f"? {prompt}")
        return self.answers.pop(0) if self.answers else default

    def confirm(self, prompt):
        self.out.append(f"? {prompt}")
        return self.confirm_answer

    @property
    def text(self):
        return "\n".join(self.out)


def test_control_codes_cover_every_slot():
    for s in SLOTS:
        assert code_to_slot(slot_to_code(s.key)) == s.key
    assert code_to_slot("e1") == "encoder_1"
    assert code_to_slot("K9") is None and code_to_slot("ZZ") is None


def test_describe_changes_names_control_and_field():
    base = USER2.read_bytes()
    t = codec.decode(base)
    t.controls["pot_3"].number = 99
    t.group_size = 2
    changes = describe_changes(base, codec.encode(t))
    assert [(c.where, c.field) for c in changes] == [
        ("header", "65 group_size"),
        ("pot_3", "+17 number"),
    ]
    assert "pot_3 [P3]" in format_changes(changes)


def test_full_simulated_session(tmp_path):
    ui = ScriptedUI()
    w = Wizard(SimulatedSL(ROOT), ui, tmp_path, ROOT, simulated=True)
    w.run()
    session = Session(tmp_path)
    assert [s.id for s in build_steps(ROOT) if not session.done(s.id)] == []
    findings = [f for s in session.data["steps"].values() for f in s["findings"]]
    # the simulator encodes our hypotheses, so nothing may contradict them
    assert not [f for f in findings if f["status"] == "warn"], ui.text
    assert any("MSB first" in f["text"] for f in findings)
    assert any("byte for byte" in f["text"] for f in findings)  # C12 round trip
    report = (tmp_path / "FINDINGS.md").read_text()
    assert "SIMULATED" in report and "## C12" in report
    assert len(codec.decode_file((tmp_path / "C0_all.syx").read_bytes())) == 40
    assert (tmp_path / "C12_sent.syx").exists()
    assert "C4" in (tmp_path / "C4.syx.md").read_text()
    # resume: nothing left to do
    again = ScriptedUI()
    Wizard(SimulatedSL(ROOT), again, tmp_path, ROOT, simulated=True).run()
    assert "━━" not in again.text and "All steps captured." in again.text


def test_skip_quit_and_resume(tmp_path):
    ui = ScriptedUI(["s", "", "", "q"])  # skip C0, do C1 (ready + notes), quit at C1b
    Wizard(SimulatedSL(ROOT), ui, tmp_path, ROOT, simulated=True).run()
    session = Session(tmp_path)
    assert not session.done("C0") and session.done("C1") and not session.done("C1b")
    assert "Still to do: C0, C1b" in ui.text
    only = ScriptedUI()
    Wizard(SimulatedSL(ROOT), only, tmp_path, ROOT, simulated=True).run(only="C4")
    assert Session(tmp_path).done("C4") and not Session(tmp_path).done("C2")


def test_cancelled_send_skips_c12(tmp_path):
    ui = ScriptedUI(confirm=False)
    w = Wizard(SimulatedSL(ROOT), ui, tmp_path, ROOT, simulated=True)
    w.run(only="C1")
    port = w.port
    w.run(only="C12")
    assert port.sent == [] and not Session(tmp_path).done("C12")


def test_nothing_received_then_skip(tmp_path):
    ui = ScriptedUI(["", "s"])  # ready, then skip after the warning
    Wizard(midi_io.FakeMidiPort(), ui, tmp_path, ROOT, timeout=0.1, preflight_checks=False).run(
        only="C1"
    )
    assert "nothing received" in ui.text and not Session(tmp_path).done("C1")


def test_c4_detects_lsb_first():
    base = USER2.read_bytes()
    sim = SimulatedSL(ROOT).dump("C4")
    data = bytearray(sim)
    off = codec.RECORD_BASE + 3 * codec.RECORD_LEN  # encoder 4
    data[off + 9], data[off + 10] = data[off + 10], data[off + 9]
    step = next(s for s in build_steps(ROOT) if s.id == "C4")
    findings = check_c4(Ctx(step, base, [bytes(data)]))
    assert findings[0].status == "warn" and "LSB FIRST" in findings[0].text


def test_misplaced_name_is_flagged():
    t = codec.decode(USER2.read_bytes())
    t.controls["pot_1"].name = "C2 E1"  # says encoder 1, sits on pot 1
    step = next(s for s in build_steps(ROOT) if s.id == "C2")
    findings = check_names(Ctx(step, USER2.read_bytes(), [codec.encode(t)]))
    assert any(f.status == "warn" and "pot_1" in f.text for f in findings)


def test_steps_match_capture_plan():
    plan = (ROOT / "docs/CAPTURE_PLAN.md").read_text()
    headings = set(re.findall(r"^### ☐ (C\d+)", plan, flags=re.M))
    ids = {s.id for s in build_steps(ROOT) if not s.id.endswith("b")}
    assert ids == headings


def test_cli_capture_requires_device_or_simulate(tmp_path):
    runner = CliRunner()
    r = runner.invoke(app, ["capture", "--folder", str(tmp_path)])
    assert r.exit_code != 0
    r = runner.invoke(
        app, ["capture", "--simulate", "--folder", str(tmp_path), "--step", "C1"], input="\n\n"
    )
    assert r.exit_code == 0, r.output
    assert "SIMULATED" in r.output and (tmp_path / "C1.syx").exists()


@pytest.mark.parametrize("step_id", ["C2", "C5", "C6", "C7"])
def test_simulated_dumps_decode(step_id):
    t = codec.decode(SimulatedSL(ROOT).dump(step_id))
    assert any(c.name.startswith(step_id + " ") for c in t.controls.values())


def test_preflight_runs_on_hardware_and_gives_up_on_a_silent_sl(tmp_path):
    ui = ScriptedUI(["", "4.1"])  # checklist, then the OS version
    w = Wizard(midi_io.FakeMidiPort(), ui, tmp_path, ROOT, timeout=0.05)
    w.preflight()
    assert "quit ableton live" in ui.text.lower() and "OS 4.1" not in ui.text
    assert Session(tmp_path).data["os_version"] == "4.1"

    silent = ScriptedUI(["", "unknown"] + ["r"] * 5)  # always answer retry
    Wizard(
        midi_io.FakeMidiPort(), silent, tmp_path, ROOT, timeout=0.02, preflight_checks=False
    ).run(only="C1")
    assert "gave up on C1" in silent.text
