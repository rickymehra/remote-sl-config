"""The SL's 40 template memories as one editable library.

A :class:`Library` holds exactly :data:`~slcfg.model.NUM_SLOTS` slots (list index 0..39 is
slot 1..40); each is a :class:`~slcfg.model.Template` or ``None`` (empty). Moving a template
rewrites its ``slot`` so the encoded header byte 12 follows; every other byte stays as loaded,
so loading a bulk dump and saving it unchanged reproduces the file exactly.

No Textual here: the TUI screen (``tui/library.py``) and the CLI drive this module.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import codec
from .model import NUM_SLOTS, Template, ValidationError

BUNDLE_FORMAT = "slcfg-bundle/1"  # same as cli.BUNDLE_FORMAT (`slcfg decode` on a bulk file)
SUFFIXES = (".syx", ".json")
# The factory bulk dump shipped in this repo; the default reference for "changed" markers.
FACTORY_BULK = (
    Path(__file__).resolve().parents[2]
    / "dumps/community/novation-factory-os41/bulk/SL_Factory_Templates_OS41.syx"
)
# Bytes before this offset hold framing, the bulk flag (7) and the slot (12); a template
# "differs" from a reference only if something from the name on differs.
COMPARE_FROM = codec.TEMPLATE_NAME_OFFSET


class LibraryError(ValueError):
    pass


@dataclass(frozen=True)
class SlotSummary:
    slot: int  # 1..40
    name: str  # whitespace collapsed for display ("" when empty)
    controls: int  # assigned controls (type != "none")
    group_size: int
    group_position: int
    empty: bool
    changed: bool | None  # vs the reference; None when there is no reference


def read_templates(path: Path) -> list[Template]:
    """Read one .syx/.json file (single template, bulk dump or bundle)."""
    try:
        if path.suffix.lower() == ".json":
            doc: dict[str, Any] = json.loads(path.read_text())
            if doc.get("format") == BUNDLE_FORMAT:
                return [Template.from_json(t) for t in doc["templates"]]
            return [Template.from_json(doc)]
        return codec.decode_file(path.read_bytes())
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise LibraryError(f"{path}: {e}") from e


def _check_slot(slot: int) -> int:
    if not isinstance(slot, int) or isinstance(slot, bool) or not 1 <= slot <= NUM_SLOTS:
        raise LibraryError(f"slot must be 1..{NUM_SLOTS}, got {slot!r}")
    return slot - 1


class Library:
    def __init__(self) -> None:
        self.slots: list[Template | None] = [None] * NUM_SLOTS

    # ---- loading ----------------------------------------------------------------------------

    @classmethod
    def from_templates(cls, templates: list[Template]) -> Library:
        """Place each template at its own ``slot``. Two templates for one slot is an error."""
        lib = cls()
        for t in templates:
            i = _check_slot(t.slot)
            if lib.slots[i] is not None:
                raise LibraryError(f"two templates for slot {t.slot}")
            lib.slots[i] = t
        return lib

    @classmethod
    def load(cls, path: Path) -> Library:
        """Load a .syx (bulk or 1..n templates), a .json template/bundle, or a folder of them."""
        if path.is_dir():
            files = sorted(p for p in path.iterdir() if p.suffix.lower() in SUFFIXES)
            if not files:
                raise LibraryError(f"{path}: no .syx or .json files")
            templates = [t for p in files for t in read_templates(p)]
        else:
            templates = read_templates(path)
        return cls.from_templates(templates)

    @classmethod
    def factory(cls) -> Library | None:
        """The factory bulk dump from this repo, or None when it is not available."""
        try:
            return cls.load(FACTORY_BULK)
        except LibraryError:
            return None

    # ---- access -----------------------------------------------------------------------------

    def get(self, slot: int) -> Template | None:
        return self.slots[_check_slot(slot)]

    def filled(self) -> list[Template]:
        return [t for t in self.slots if t is not None]

    def _renumber(self) -> None:
        for i, t in enumerate(self.slots):
            if t is not None:
                t.slot = i + 1

    # ---- editing ----------------------------------------------------------------------------

    def put(self, slot: int, template: Template) -> None:
        """Store a copy of ``template`` in ``slot`` (replacing what was there)."""
        i = _check_slot(slot)
        t = copy.deepcopy(template)
        t.slot = slot
        try:
            t.validate()
        except ValidationError as e:
            raise LibraryError(str(e)) from e
        self.slots[i] = t

    def import_file(self, slot: int, path: Path) -> Template:
        """Put the single template in ``path`` into ``slot``."""
        ts = read_templates(path)
        if len(ts) != 1:
            raise LibraryError(f"{path} holds {len(ts)} templates; import takes one")
        self.put(slot, ts[0])
        return self.slots[slot - 1]  # type: ignore[return-value]

    def clear(self, slot: int) -> None:
        self.slots[_check_slot(slot)] = None

    def swap(self, a: int, b: int) -> None:
        i, j = _check_slot(a), _check_slot(b)
        self.slots[i], self.slots[j] = self.slots[j], self.slots[i]
        self._renumber()

    def move(self, src: int, dst: int) -> None:
        """Take the template out of ``src`` and insert it at ``dst``; the slots in between
        shift by one towards ``src`` (list-style reorder, empty slots move too)."""
        i, j = _check_slot(src), _check_slot(dst)
        self.slots.insert(j, self.slots.pop(i))
        self._renumber()

    # ---- output -----------------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """All non-empty slots, encoded in slot order (a bulk dump when all 40 are filled)."""
        return codec.encode_file(self.filled())

    def save_bulk(self, path: Path) -> int:
        if not self.filled():
            raise LibraryError("library is empty")
        path.write_bytes(self.to_bytes())
        return len(self.filled())

    def export(self, slot: int, path: Path) -> None:
        """Write one slot as .syx or .json (chosen by the suffix of ``path``)."""
        t = self.get(slot)
        if t is None:
            raise LibraryError(f"slot {slot} is empty")
        if path.suffix.lower() == ".json":
            path.write_text(json.dumps(t.to_json(), indent=2) + "\n")
        elif path.suffix.lower() == ".syx":
            path.write_bytes(codec.encode(t))
        else:
            raise LibraryError(f"{path}: export needs a .syx or .json suffix")

    # ---- inspection -------------------------------------------------------------------------

    def differs(self, slot: int, reference: Library) -> bool:
        """True if ``slot`` holds something other than ``reference`` has there, comparing the
        encoded bytes from the name on (framing, bulk flag and slot number are ignored)."""
        a, b = self.get(slot), reference.get(slot)
        if a is None or b is None:
            return (a is None) != (b is None)
        return codec.encode(a)[COMPARE_FROM:] != codec.encode(b)[COMPARE_FROM:]

    def summary(self, slot: int, reference: Library | None = None) -> SlotSummary:
        t = self.get(slot)
        changed = None if reference is None else self.differs(slot, reference)
        if t is None:
            return SlotSummary(slot, "", 0, 0, 0, True, changed)
        used = sum(1 for c in t.controls.values() if c.type != "none")
        name = " ".join(t.name.split())
        return SlotSummary(slot, name, used, t.group_size, t.group_position, False, changed)
