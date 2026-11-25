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
ID_TYPE_WEAPON = 1
ID_TYPE_ARMOR = 2
ID_TYPE_TALISMAN = 3
# Equipment pack / My Set inventory index lists: weapon, head, chest, arm, waist, leg, petalace, talisman.
PACK_WEAPON, PACK_ARMOR, PACK_TALISMAN = 0, slice(1, 6), 7


class SaveDataError(Exception):
    pass


def hunter_sex(save: SaveFile) -> int | None:
    """Read the hunter's own guild card, never a received hunter's card."""
    for manager in save.walk_classes("snow.GuildCardManager.GuildCardSaveData"):
        card = manager.get("MyData")
        value = card.get("Sex") if isinstance(card, Class) else None
        if isinstance(value, Scalar) and value.u in (0, 1):
            return value.u
    return None


def armor_for_hunter(data: dict, sex: int | None) -> dict:
    """Keep the full catalog intact so switching hunters restores their armor."""
    return {**data, **{key: {aid: a for aid, a in data[key].items()
                            if sex is None or a.get("sex", 2) in (sex, 2)}
                      for key in ("armors", "all_armors")}}


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
    index: int = -1                  # position in the equipment box
    decos: list = None               # decoration ids slotted in it


@dataclass
class TalismanItem:
    skills: list                     # [(skill, level)]
    slots: list                      # 3 slot levels, highest first
    index: int = -1
    decos: list = None


@dataclass
class WeaponItem:
    weapon_id: int
    index: int
    decos: list


@dataclass
class Loadout:
    name: str
    weapon: int | None               # box indices (None = nothing equipped there)
    armor: list                      # 5 box indices or None, head..leg
    talisman: int | None
    decos: dict                      # box index -> decoration ids as slotted in this loadout


def box_items(save: SaveFile, data: dict) -> tuple[list[ArmorItem], list[TalismanItem]]:
    """Every armor piece and talisman in the equipment box, with the qurious augments of each piece."""
    base = {(b["table"], b["id"]): b for b in data["base"]}
    armors, talismans = [], []
    for pos, v in enumerate(inventory(save)):
        if not isinstance(v, Class):
            continue
        kind = v["_IdType"].s
        if kind == ID_TYPE_ARMOR:
            aid = v["_IdVal"].u
            if str(aid) not in data["all_armors"]:
                continue
            item = ArmorItem(aid, bool(v["_CustomEnable"].b), resistances=[0] * 5, skills=[], index=pos,
                             decos=[x.u for x in v["_DecoIdList"]])
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
                talismans.append(TalismanItem(skills, (slots + [0, 0, 0])[:3], pos, [x.u for x in v["_DecoIdList"]]))
    return armors, talismans


def box_weapons(save: SaveFile) -> list[WeaponItem]:
    return [WeaponItem(v["_IdVal"].u, pos, [x.u for x in v["_DecoIdList"]])
            for pos, v in enumerate(inventory(save)) if isinstance(v, Class) and v["_IdType"].s == ID_TYPE_WEAPON]


def owned_decorations(save: SaveFile) -> Counter:
    """Decoration id -> how many the hunter has: in the decoration box plus slotted in equipment."""
    out = Counter()
    for dm in save.walk_classes("snow.data.DataManager.SaveData1"):
        for d in dm["_PlDecoBoxInventoryDataList"]:
            if d["_Id"].u and d["_Num"].u:
                out[d["_Id"].u] += d["_Num"].u
        break
    for v in inventory(save):
        if isinstance(v, Class) and v["_IdType"].s in (ID_TYPE_WEAPON, ID_TYPE_ARMOR, ID_TYPE_TALISMAN):
            for x in v["_DecoIdList"]:
                if x.u:
                    out[x.u] += 1
    return out


def loadouts(save: SaveFile) -> list[Loadout]:
    """The equipment the hunter wears now, then every saved equipment loadout (My Set)."""
    box = inventory(save)

    def idx(v):
        return v if 0 <= v < len(box) else None

    def decos_of(i):
        return [x.u for x in box[i]["_DecoIdList"]] if i is not None else []

    out = []
    for dm in save.walk_classes("snow.data.EquipDataManager.SaveData1"):
        pack = [idx(x.s) for x in dm["_PlEquipPack"]["_InventoryIndexList"]]
        if len(pack) >= 8:
            used = [pack[PACK_WEAPON], *pack[PACK_ARMOR], pack[PACK_TALISMAN]]
            out.append(Loadout("Equipped now", pack[PACK_WEAPON], pack[PACK_ARMOR], pack[PACK_TALISMAN],
                               {i: decos_of(i) for i in used if i is not None}))
        for n, m in enumerate(dm["_PlEquipMySetList"], 1):
            if not m["_IsUsing"].b:
                continue
            ids = [idx(x.s) for x in m["_InventoryIndexList"]]
            if len(ids) < 8 or all(i is None for i in ids[PACK_ARMOR]):
                continue
            backup = m["_BackupDataList"]
            decos = {}
            for k in [PACK_WEAPON, 1, 2, 3, 4, 5, PACK_TALISMAN]:
                i = ids[k]
                if i is None:
                    continue
                saved = [x.u for x in backup[k]["DecoIdList"]] if k < len(backup) else []
                decos[i] = saved if any(saved) else decos_of(i)
            out.append(Loadout(f"{n}. {m['_Name'] or 'My Set'}", ids[PACK_WEAPON], ids[PACK_ARMOR], ids[PACK_TALISMAN], decos))
        break
    return out
