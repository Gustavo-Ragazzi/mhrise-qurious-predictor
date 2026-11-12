"""What the predictor needs from a character save (read-only): generator states and armor."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from mhrise_exporter.export import inventory
from mhrise_exporter.save import Class, Scalar, SaveFile, hash_utf8

from .rng import XorShift128

FACILITY_SAVE = hash_utf8("snow.data.FacilityDataManager.SaveData")
# FacilityDataManager.SaveData field holding the 56 RandomSeedManual generator states (GUIDs).
# The name is unknown; it is the only 56-entry GUID list in that class.
MANUAL_STATES_FIELD = 0x38CB095F
MANUAL_COUNT = 56
ID_TYPE_ARMOR = 2


class SaveDataError(Exception):
    pass


def manual_generators(save: SaveFile) -> list[XorShift128]:
    """FacilityDataManager._RandomManual, as stored in the save."""
    for _, c in save.entries:
        if c.hash != FACILITY_SAVE:
            continue
        fields = [(fh, v) for fh, _, v in c.fields
                  if isinstance(v, list) and len(v) == MANUAL_COUNT and v and isinstance(v[0], Scalar)
                  and len(v[0].raw) == 16]
        fields.sort(key=lambda f: f[0] != MANUAL_STATES_FIELD)
        if fields:
            return [XorShift128.from_bytes(s.raw) for s in fields[0][1]]
    raise SaveDataError("random generator states not found in the save (FacilityDataManager.SaveData)")


@dataclass
class OwnedArmor:
    armor_id: int
    count: int
    augmented: int  # how many of them already have qurious crafting


def owned_armor(save: SaveFile) -> list[OwnedArmor]:
    count, aug = Counter(), Counter()
    for v in inventory(save):
        if not isinstance(v, Class) or v["_IdType"].s != ID_TYPE_ARMOR:
            continue
        aid = v["_IdVal"].u
        count[aid] += 1
        if v["_CustomEnable"].b:
            aug[aid] += 1
    return [OwnedArmor(a, n, aug[a]) for a, n in count.items()]
