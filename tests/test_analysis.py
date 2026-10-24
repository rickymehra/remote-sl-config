from slcfg.analysis import ascii_runs, inspect_bytes, label_candidates, stride_scores


def test_stride_detects_record_size(fixtures):
    data = (fixtures / "stride24_a.syx").read_bytes()
    assert stride_scores(data)[0][0] == 24


def test_labels_and_record_base(fixtures):
    data = (fixtures / "two_messages.syx").read_bytes()
    reports = inspect_bytes(data)
    assert len(reports) == 2
    r = reports[1]
    assert len(r.labels) == 10
    assert r.labels[0].text == "Ctl 00  "
    assert r.label_stride == 41
    assert r.stride == 41
    assert r.record_base == 20


def test_ascii_runs_ignore_blank():
    runs = ascii_runs(b"\x00    \x00abc\x00ab\x00")
    assert [(r.offset, r.text) for r in runs] == [(6, "abc")]


def test_back_to_back_labels_are_split():
    labs = label_candidates(b"\x00Osc1LevlOsc1Semi\x00")
    assert [lab.text for lab in labs] == ["Osc1Levl", "Osc1Semi"]


def test_real_template_stride(vstation):
    (r,) = inspect_bytes(vstation)
    assert r.label_stride == 41
    assert r.record_base == 419
