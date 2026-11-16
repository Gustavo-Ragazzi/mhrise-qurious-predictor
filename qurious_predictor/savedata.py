"""What the predictor needs from a character save (read-only): generator states and armor."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from mhrise_exporter.export import RES_BLOCKS, inventory
from mhrise_exporter.save import Class, Scalar, SaveFile, hash_utf8

from . import engine
from .rng import XorShift128

FACILITY_SAVE = hash_utf8("snow.data.FacilityDataManager.SaveData")
# FacilityDataManager.SaveData field holding the 56 RandomSeedManual generator states (GUIDs).
# The name is unknown; it is the only 56-entry GUID list in that class.
MANUAL_STATES_FIELD = 0x38CB095F
MANUAL_COUNT = 56
ID_TYPE_ARMOR = 2
ID_TYPE_TALISMAN = 3


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


@dataclass
class ArmorItem:
    armor_id: int
    augmented: bool
    defense: int = 0                 # qurious changes
    resistances: list = None         # fire, water, thunder, ice, dragon
    slot_points: int = 0
    skills: list = None              # [(skill, +/- levels)], in augment order


@dataclass
class TalismanItem:
    skills: list                     # [(skill, level)]
    slots: list                      # 3 slot levels, highest first


def box_items(save: SaveFile, data: dict) -> tuple[list[ArmorItem], list[TalismanItem]]:
    """Every armor piece and talisman in the equipment box, with the qurious augments of each piece."""
    base = {(b["table"], b["id"]): b for b in data["base"]}
    armors, talismans = [], []
    for v in inventory(save):
        if not isinstance(v, Class):
            continue
        kind = v["_IdType"].s
        if kind == ID_TYPE_ARMOR:
            aid = v["_IdVal"].u
            if str(aid) not in data["all_armors"]:
                continue
            item = ArmorItem(aid, bool(v["_CustomEnable"].b), resistances=[0] * 5, skills=[])
            table = data["armors"].get(str(aid), {}).get("table")
            if item.augmented and table:
                for b in v["_CustomBuildup"]:
                    bid = b["_Id"].u
                    p = base.get((table, bid)) if bid else None
                    if p is None:
                        continue
                    value = p["values"][b["_ValueIndex"].u]
                    cat = p["category"]
                    if cat == engine.CAT_DEF:
                        item.defense += value
                    elif cat in (engine.CAT_RES, engine.CAT_RES_PENALTY):
                        for i, (lo, hi) in enumerate(RES_BLOCKS):
                            if lo <= bid <= hi:
                                item.resistances[i] += value
                    elif cat == engine.CAT_SLOT:
                        item.slot_points += value
                    elif cat == engine.CAT_SKILL:
                        item.skills.append((b["_SkillId"].u, value))
            armors.append(item)
        elif kind == ID_TYPE_TALISMAN:
            sk = [x.u for x in v["_TalismanSkillIdList"]]
            lv = [x.u for x in v["_TalismanSkillLvList"]]
            deco = [x.u for x in v["_TalismanDecoSlotNumList"]]   # index = slot level
            slots = []
            for level in (4, 3, 2, 1):
                slots += [level] * (deco[level] if level < len(deco) else 0)
            skills = [(s, l) for s, l in zip(sk, lv) if s and l]
            if skills:
                talismans.append(TalismanItem(skills, (slots + [0, 0, 0])[:3]))
    return armors, talismans
