"""Which controls of an Automap template belong to Automap, so the editor can lock them.

The template data has no "Automap" flag: in template 40 most controls are plain CC
messages, and what makes them Automap is the DAW's control-surface script listening for
those CCs on USB port 2 (or the Automap Server on port 3). So the lock is a per-template
map from the ReMOTE SL user guide plus two signals seen in every factory Automap template:

* free: controls routed with the keyboard (port code 0x20, guessed to mean KeybPORT: pedals,
  joystick, and pads in some templates). The guide says keyboard, joystick and pedals never
  follow Automap.
* free: controls the guide names as user-assignable for that template (Ableton: pots, the
  lower left-hand button row and the drum pads).
* locked: everything else, including controls whose role the guide does not document.
  "Locked" means "probably Automap"; the TUI toggle unlocks them.
"""

from __future__ import annotations

from .model import SLOT_BY_KEY, Template

KEYBOARD_PORT = 0x20  # port code on pedals/joystick in Automap templates (FORMAT.md +18)
KEYBOARD_GROUPS = frozenset({"pedal", "joystick"})

# profile -> control groups the user guide documents as free in that template
FREE_GROUPS: dict[str, frozenset[str]] = {
    "ableton": frozenset({"pot", "button_row2", "drum_pad"}),  # guide §10.2
    "logic": frozenset(),
    "reason": frozenset(),
    "protools": frozenset(),
    "universal": frozenset(),
}
# factory slot of each Automap template (guide §5.4: 34 and 37-40)
FACTORY_SLOTS = {34: "protools", 37: "reason", 38: "universal", 39: "logic", 40: "ableton"}


def profile(t: Template) -> str | None:
    """Automap profile of a template from its name, or None for a standard template."""
    name = t.name.lower()
    if "automap" not in name:
        return None
    for key in ("ableton", "logic", "reason", "protools", "pro tools"):
        if key in name:
            return key.replace(" ", "")
    return "universal"


def locked_slots(t: Template) -> set[str]:
    """Slot keys to lock in ``t`` (empty for standard templates)."""
    prof = profile(t)
    if prof is None:
        return set()
    free = FREE_GROUPS[prof] | KEYBOARD_GROUPS
    locked = set()
    for key, c in t.controls.items():
        if SLOT_BY_KEY[key].group in free or c.port == KEYBOARD_PORT:
            continue
        locked.add(key)
    return locked
