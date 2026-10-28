from pathlib import Path

from slcfg import codec, probe

USER2 = Path(__file__).parent.parent / "dumps/community/novation-factory-os41/36_-_-_User2.syx"


def test_build_and_analyse_round_trip():
    data, plan = probe.build(USER2.read_bytes(), "port")
    t = codec.decode(data)
    assert data[codec.BULK_FLAG_OFFSET] == 0
    assert len(plan) == len(probe.CODES) and sorted(plan.values()) == sorted(probe.CODES)
    for key, c in t.controls.items():
        i = codec.m.SLOT_BY_KEY[key].index
        if i in plan:
            assert (c.type, c.number, c.port, c.channel) == ("cc", i, plan[i], 0)
        else:
            assert c.type == "none"
    # CC 3 on channel 5 via Port 2; a non-CC message and an unknown CC are ignored
    events = [("Port 2", [0xB4, 3, 64]), ("Port 2", [0x90, 3, 64]), ("Port 1", [0xB0, 99, 1])]
    res = probe.analyse(events, plan)
    assert res[plan[3]] == {"ports": {"Port 2"}, "channels": {5}, "count": 1}
    assert sum(r["count"] for r in res.values()) == 1
    assert "nothing over USB" in probe.report("port", res)


def test_build_header_override():
    data, _ = probe.build(USER2.read_bytes(), "chan", 0x44, {102: 0x50})
    assert data[102] == 0x50
    assert codec.decode(data).controls["encoder_1"].port == 0x44
