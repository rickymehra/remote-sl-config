"""The 40-slot library: loading, reordering, import/export, byte-exact bulk save."""

import json

import pytest

from conftest import BULK, V_STATION_1
from slcfg import codec
from slcfg.cli import _templates_to_json
from slcfg.library import Library, LibraryError
from slcfg.model import NUM_SLOTS


@pytest.fixture
def factory() -> Library:
    return Library.load(BULK)


def test_bulk_roundtrip_is_byte_exact(factory, tmp_path):
    assert all(t is not None for t in factory.slots)
    assert [t.slot for t in factory.filled()] == list(range(1, NUM_SLOTS + 1))
    out = tmp_path / "out.syx"
    assert factory.save_bulk(out) == NUM_SLOTS
    assert out.read_bytes() == BULK.read_bytes()


def test_swap_updates_slot_bytes(factory):
    a, b = factory.get(1), factory.get(2)
    factory.swap(1, 2)
    assert factory.get(1) is b and factory.get(2) is a
    assert (a.slot, b.slot) == (2, 1)
    data = factory.to_bytes()
    first, second = data[: codec.MESSAGE_LEN], data[codec.MESSAGE_LEN : 2 * codec.MESSAGE_LEN]
    assert first[codec.SLOT_OFFSET] == 0 and second[codec.SLOT_OFFSET] == 1
    assert first[13:].startswith(b"V-Station-2") and second[13:].startswith(b"V-Station-1")
    # only the slot bytes changed
    orig = BULK.read_bytes()
    swapped = orig[codec.MESSAGE_LEN : 2 * codec.MESSAGE_LEN] + orig[: codec.MESSAGE_LEN]
    assert [i for i in range(2 * codec.MESSAGE_LEN) if data[i] != swapped[i]] == [
        codec.SLOT_OFFSET,
        codec.MESSAGE_LEN + codec.SLOT_OFFSET,
    ]
    assert data[2 * codec.MESSAGE_LEN :] == orig[2 * codec.MESSAGE_LEN :]
    factory.swap(1, 2)
    assert factory.to_bytes() == orig


def test_move_shifts_the_slots_between(factory):
    names = [t.name for t in factory.filled()]
    factory.move(1, 4)
    assert [t.name for t in factory.filled()][:4] == [names[1], names[2], names[3], names[0]]
    assert [t.slot for t in factory.filled()] == list(range(1, NUM_SLOTS + 1))
    data = factory.to_bytes()
    assert data[3 * codec.MESSAGE_LEN + codec.SLOT_OFFSET] == 3
    factory.move(4, 1)
    assert factory.to_bytes() == BULK.read_bytes()


def test_empty_slots_and_partial_files(tmp_path):
    lib = Library.load(V_STATION_1)
    filled = [i + 1 for i, t in enumerate(lib.slots) if t is not None]
    assert len(filled) == 1
    slot = filled[0]
    s = lib.summary(2 if slot != 2 else 3)
    assert s.empty and s.name == "" and s.controls == 0 and s.changed is None
    lib.clear(slot)
    assert lib.filled() == []
    with pytest.raises(LibraryError, match="empty"):
        lib.save_bulk(tmp_path / "x.syx")
    with pytest.raises(LibraryError, match="empty"):
        lib.export(slot, tmp_path / "x.syx")
    with pytest.raises(LibraryError, match="1..40"):
        lib.get(41)
    # empty slots move like any other
    lib.put(5, codec.decode(V_STATION_1.read_bytes()))
    lib.move(5, 1)
    assert lib.get(1).slot == 1 and lib.get(5) is None


def test_import_and_export(factory, tmp_path):
    t = factory.import_file(40, V_STATION_1)
    assert t.slot == 40 and factory.get(40) is t
    assert codec.encode(t)[codec.SLOT_OFFSET] == 39
    assert not factory.differs(1, factory) and not factory.differs(40, factory)
    factory.export(40, tmp_path / "v.syx")
    factory.export(40, tmp_path / "v.json")
    assert (tmp_path / "v.syx").read_bytes()[13:] == V_STATION_1.read_bytes()[13:]
    assert json.loads((tmp_path / "v.json").read_text())["slot"] == 40
    with pytest.raises(LibraryError, match="suffix"):
        factory.export(40, tmp_path / "v.txt")
    with pytest.raises(LibraryError, match="40 templates"):
        factory.import_file(1, BULK)


def test_summary_and_changed_vs_reference(factory):
    ref = Library.load(BULK)
    s = factory.summary(1, ref)
    assert s.name == "V-Station-1 Novation" and s.controls == 41
    assert (s.group_size, s.group_position, s.changed) == (3, 1, False)
    factory.get(1).name = "Mine"
    assert factory.summary(1, ref).changed is True
    factory.swap(2, 3)  # different template at those slots now
    assert factory.differs(2, ref) and factory.differs(3, ref)
    factory.clear(4)
    assert factory.summary(4, ref).changed is True
    assert Library.factory() is not None


def test_load_bundle_and_folder(factory, tmp_path):
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps(_templates_to_json(factory.filled())))
    assert Library.load(bundle).to_bytes() == BULK.read_bytes()

    folder = tmp_path / "lib"
    folder.mkdir()
    for slot in (1, 7, 40):
        factory.export(slot, folder / f"{slot:02d}.{'json' if slot == 7 else 'syx'}")
    (folder / "notes.txt").write_text("ignored")
    lib = Library.load(folder)
    assert [i + 1 for i, t in enumerate(lib.slots) if t is not None] == [1, 7, 40]
    for slot in (1, 7, 40):
        assert codec.encode(lib.get(slot)) == codec.encode(factory.get(slot))


def test_load_errors(tmp_path):
    (tmp_path / "a.syx").write_bytes(V_STATION_1.read_bytes())
    (tmp_path / "b.syx").write_bytes(V_STATION_1.read_bytes())
    with pytest.raises(LibraryError, match="two templates"):
        Library.load(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(LibraryError, match="no .syx"):
        Library.load(empty)
    (tmp_path / "bad.json").write_text("{not json")
    with pytest.raises(LibraryError, match="bad.json"):
        Library.load(tmp_path / "bad.json")
