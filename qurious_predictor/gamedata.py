"""Static tables read from the user's own game install, cached as JSON (nothing from Capcom ships)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from mhrise_exporter import rsz
from mhrise_exporter.gamedata import PARTS, _msg_map, _names, skill_msg_tag
from mhrise_exporter.pak import open_game_paks

from .engine import Buildup, Tables

CACHE_VERSION = 8
DIR = "data/Define/Player/Equip/CustomBuildup"

# Extra RSZ layouts (v16), from the kvasszn/ree-save-editor type dump.
rsz.SPECS.update({
    "snow.data.CustomBuildupArmorLotUserData": (None, [("_Param", "obj", True)]),
    "snow.data.CustomBuildupArmorLotUserData.Param": (None, [
        ("_TableNo", "u32", False), ("_CategoryId", "u16", False), ("_Id", "u16", False),
        ("_LotNum", "u32", False),
    ]),
    "snow.data.CustomBuildupArmorCategoryLotUserData": (None, [("_Param", "obj", True)]),
    "snow.data.CustomBuildupArmorCategoryLotUserData.Param": (None, [
        ("_TableNo", "u32", False), ("_LotNum", "u32", True),
    ]),
    "snow.data.CustomBuildupEquipSkillDetailUserData": (None, [("_Param", "obj", True)]),
    "snow.data.CustomBuildupEquipSkillDetailUserData.Param": (None, [
        ("_SkillId", "u8", False), ("_Cost", "u32", False),
    ]),
    "snow.data.PlEquipSkillBaseUserData": (None, [("_Param", "obj", True)]),
    "snow.data.PlEquipSkillBaseUserData.Param": (None, [
        ("_Id", "u8", False), ("_MaxLevel", "s32", False), ("_IconColor", "s32", False),
        ("_CategoryId_1", "u16", False), ("_CategoryId_2", "u16", False), ("_CategoryId_3", "u16", False),
    ]),
    # Talisman (melding) skill table; layout from wwylele/mhrice src/rsz/alchemy.rs.
    "snow.data.AlchemyPlSkillTableUserData": (None, [("_Param", "obj", True)]),
    "snow.data.AlchemyPlSkillTableUserData.Param": (None, [
        ("_SortId", "s32", False), ("_SkillId", "u8", False), ("_Grade", "s32", False), ("_Patturn", "s32", False),
        ("_PickRate", "u32", False), ("_GradePickRate", "u32", True), ("_Skill1RateList", "u32", True),
        ("_MissRateList", "u32", True), ("_Skill2RateList", "u32", True), ("_Skill1MysteryWorth", "u32", True),
        ("_Skill2MysteryWorth", "u32", True),
    ]),
    # The other melding tables; v16 layouts from the alphazolam/RE_RSZ type dump (mhrice predates v16
    # for AlchemyPatturn and SlotNumTable).
    "snow.data.alchemy.SkillGradeLotRateTableUserData": (None, [("_Param", "obj", True)]),
    "snow.data.alchemy.SkillGradeLotRateTableUserData.Param": (None, [
        ("_PatturnType", "s32", False), ("_Probability1List", "u32", True), ("_ProbabilityList", "u32", True),
        ("_Probability2List", "u32", True),
    ]),
    "snow.data.alchemy.SecondSkillLotRateTableUserData": (None, [("_Param", "obj", True)]),
    "snow.data.alchemy.SecondSkillLotRateTableUserData.Param": (None, [
        ("_Skill1Grade", "s32", False), ("_ProbabilityList", "u32", True),
    ]),
    "snow.data.alchemy.SlotNumTableUserData": (None, [("_Param", "obj", True)]),
    "snow.data.alchemy.SlotNumTableUserData.SlotParam": (None, [("_SlotParam", "obj", True)]),
    "snow.data.alchemy.SlotNumTableUserData.SkillParam": (None, [
        ("_Skill1Grade", "s32", False), ("_Skill2Grade", "s32", False),
        *[(f"_Table{i}ProbabilityList", "u32", True) for i in range(8)],
    ]),
    "snow.data.alchemy.MysterySlotNumTableUserData": (None, [("_MysterySkillParam", "obj", True)]),
    "snow.data.alchemy.MysterySlotNumTableUserData.MysterySkillParam": (None, [
        ("_PickRate", "u32", False), ("_SlotLv", "u32", True), ("_MysteryWorth", "u32", False),
    ]),
})
# Armor upgrade table (max defense) and weapon base data, layouts as in mhrise-set-builder (v16).
rsz.SPECS.update({
    "snow.data.ArmorBuildupTableUserData": (None, [("_Param", "obj", True)]),
    "snow.data.ArmorBuildupTableUserData.Param": (None, [
        ("_TableType", "s32", False), ("_VillageProgress", "s32", False), ("_HallProgress", "s32", False),
        ("_MRProgress", "s32", False), ("_LimitLv", "u32", False), ("_LvUpRate", "s32", False),
        ("_UpVal", "s32", False), ("_Cost", "s32", False), ("_MaxCost", "s32", False),
    ]),
})
WEAPON_TYPES = ["GreatSword", "ShortSword", "Hammer", "Lance", "LongSword", "SlashAxe", "GunLance", "DualBlades",
                "Horn", "InsectGlaive", "ChargeAxe", "LightBowgun", "HeavyBowgun", "Bow"]
_W_COMMON = [
    ("_Id", "u32", False), ("_SortId", "u32", False), ("_RareType", "u8", False), ("_ModelId", "u32", False),
    ("_BaseVal", "u32", False), ("_BuyVal", "u32", False), ("_Atk", "s32", False), ("_CriticalRate", "s32", False),
    ("_DefBonus", "s32", False), ("_HyakuryuSkillIdList", "s32", True), ("_SlotNumList", "u32", True),
    ("_HyakuryuSlotNumList", "u32", True), ("_CustomTableNo", "u32", False), ("_CustomCost", "u32", False),
]
_W_ELEMENT = [("_MainElementType", "s32", False), ("_MainElementVal", "s32", False)]
_W_SHARP = [("_SharpnessValList", "s32", True), ("_TakumiValList", "s32", True)]
_W_BULLET = [
    ("_Fluctuation", "s32", False), ("_Reload", "s32", False), ("_Recoil", "s32", False), ("_KakusanType", "s32", False),
    ("_BulletEquipFlagList", "bool", True), ("_BulletNumList", "u32", True), ("_BulletTypeList", "s32", True),
]
_W_TAIL = {
    "SlashAxe": [("_SlashAxeBottleType", "u32", False), ("_SlashAxeBottleElementVal", "s32", False)],
    "GunLance": [("_GunLanceFireType", "s32", False), ("_GunLanceFireLv", "s32", False)],
    "Horn": [("_HornMelodyTypeList", "s32", True)],
    "InsectGlaive": [("_InsectGlaiveInsectLv", "s32", False)],
    "ChargeAxe": [("_ChargeAxeBottleType", "u32", False)],
    "DualBlades": [("_SubElementType", "s32", False), ("_SubElementVal", "s32", False)],
}


def _weapon_fields(cls: str) -> list:
    if cls == "LightBowgun":
        return _W_COMMON + _W_BULLET + [("_RapidShotList", "u32", True), ("_UniqueBullet", "u32", False)]
    if cls == "HeavyBowgun":
        return _W_COMMON + _W_BULLET + [("_HeavyBowgunUniqueBulletType", "s32", False)]
    if cls == "Bow":
        return _W_COMMON + _W_ELEMENT + [
            ("_BowBottlePowerUpTypeList", "u32", True), ("_BowBottleEquipFlagList", "bool", True),
            ("_BowDefaultChargeLvLimit", "s32", False), ("_BowChargeTypeList", "s32", True), ("_BowCurveType", "s32", False)]
    return _W_COMMON + _W_ELEMENT + _W_SHARP + _W_TAIL.get(cls, [])


for _cls in WEAPON_TYPES:
    rsz.SPECS[f"snow.equip.{_cls}BaseUserData"] = (None, [("_Param", "obj", True)])
    rsz.SPECS[f"snow.equip.{_cls}BaseUserData.Param"] = (None, _weapon_fields(_cls))
rsz._BY_HASH.update({rsz.hash_utf8(name): name for name in rsz.SPECS})


def default_cache_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "mhrise-qurious-predictor"


def build(game_dir: Path, log=print) -> dict:
    pak = open_game_paks(game_dir)
    try:
        log("Reading Qurious Crafting tables...")

        def params(name):
            return rsz.parse_user(pak.read_any(f"{DIR}/{name}.user", ["2"]))[0]["_Param"]

        base = [dict(table=p["_TableNo"], id=p["_Id"], category=p["_CategoryId"], cost=p["_Cost"],
                     values=p["_ValueTable"], lots=p["_LotTable"])
                for p in params("CustomBuildupBaseUserData")]
        armor_lots = [(p["_TableNo"], p["_CategoryId"], p["_Id"], p["_LotNum"])
                      for p in params("CustomBuildupArmorLotUserData")]
        category_lots = {str(p["_TableNo"]): p["_LotNum"] for p in params("CustomBuildupArmorCategoryLotUserData")}
        skill_costs = [(p["_SkillId"], p["_Cost"]) for p in params("CustomBuildupEquipSkillDetailUserData")]

        skill_base = rsz.parse_user(pak.read_any(
            "data/Define/Player/Skill/PlEquipSkill/PlEquipSkillBaseData.user", ["2"]))[0]["_Param"]
        max_levels = {str(p["_Id"]): p["_MaxLevel"] for p in skill_base}
        skill_colors = {str(p["_Id"]): p["_IconColor"] for p in skill_base}

        log("Reading decorations and talisman skills...")
        deco_levels = {}  # skill -> lowest decoration level that gives a point of it
        for p in rsz.parse_user(pak.read_any(
                "data/Define/Player/Equip/Decorations/DecorationsBaseData.user", ["2"]))[0]["_Param"]:
            for sid in p["_SkillIdList"]:
                if sid:
                    deco_levels[str(sid)] = min(deco_levels.get(str(sid), 99), p["_DecorationLv"])
        def alchemy(name):
            return rsz.parse_user(pak.read_any(f"data/Define/Lobby/Facility/Alchemy/{name}.user", ["2"]))[0]

        skill_table = alchemy("AlchemyPlSkillTable")["_Param"]
        talisman_skills = sorted({p["_SkillId"] for p in skill_table
                                  if p["_SkillId"] and (p["_PickRate"] or any(p["_Skill1RateList"]) or any(p["_Skill2RateList"]))})
        log("Reading melding tables...")
        melding = {
            # per method (pattern), in table order: skill, grade, pick rate, grade pick rates, level tables
            "skills": [[p["_Patturn"], p["_SkillId"], p["_Grade"], p["_PickRate"], list(p["_GradePickRate"]),
                        list(p["_Skill1RateList"]), list(p["_MissRateList"]), list(p["_Skill2RateList"])]
                       for p in skill_table],
            "grades": {str(p["_PatturnType"]): [p["_Probability1List"], p["_ProbabilityList"], p["_Probability2List"]]
                       for p in alchemy("SkillGradeLotRateTable")["_Param"]},
            "second": {str(p["_Skill1Grade"]): p["_ProbabilityList"] for p in alchemy("SecondSkillLotRateTable")["_Param"]},
            "slots": [[[q["_Skill1Grade"], q["_Skill2Grade"], [q[f"_Table{i}ProbabilityList"] for i in range(8)]]
                       for q in block["_SlotParam"]] for block in alchemy("SlotNumTable")["_Param"]],
            "mystery_slots": [[q["_PickRate"], q["_SlotLv"]] for q in alchemy("MysterySlotNumTable")["_MysterySkillParam"]],
        }

        log("Reading skill names...")
        msg = "data/Define/Player/Skill/PlEquipSkill/PlayerSkill_Name"
        sk, sk_mr = _msg_map(pak, msg), _msg_map(pak, msg + "_MR")
        skills = {}
        for sid in range(1, 256):
            tag = skill_msg_tag(sid)
            names = _names(sk_mr.get(f"{tag}_Name_MR") or sk_mr.get(f"{tag}_Name") or sk.get(f"{tag}_Name"))
            if names:
                skills[str(sid)] = names

        log("Reading armor data...")
        armor_msgs = {}
        for part in PARTS:
            for suffix in ("", "_MR"):
                armor_msgs.update(_msg_map(pak, f"data/Define/Player/Armor/{part}/A_{part}_Name{suffix}"))
        upgrades = {}   # upgrade table -> defense gained from level 1 to the last level
        rows = {}
        for p in rsz.parse_user(pak.read_any("data/System/ContentsIdSystem/Armor/ArmorBuildupTableData.user", ["2"]))[0]["_Param"]:
            rows.setdefault(p["_TableType"], []).append((p["_LimitLv"], p["_UpVal"]))
        for t, r in rows.items():
            prev, total = 1, 0
            for limit, up in sorted(r):
                total += max(limit - prev, 0) * up
                prev = max(prev, limit)
            upgrades[t] = total
        armors, all_armors = {}, {}
        for p in rsz.parse_user(pak.read_any("data/Define/Player/Armor/ArmorBaseData.user", ["2"]))[0]["_Param"]:
            aid = p["_Id"]
            kind = (aid >> 20) & 0xF
            if not p["_IsValid"] or not 1 <= kind <= 5:
                continue
            # every armor piece, for the inventory tab
            all_armors[str(aid)] = {
                "names": _names(armor_msgs.get(f"A_{PARTS[kind - 1]}_{aid & 0xFFFF:03}_Name")),
                "skills": [[s, lv] for s, lv in zip(p["_SkillList"], p["_SkillLvList"]) if s],
                "slots": p["_DecorationsNumList"],
                "part": kind - 1,
                "rare": p["_Rare"],
                "def": p["_DefVal"],
                "defMax": p["_DefVal"] + upgrades.get(p["_BuildupTable"], 0),
                "res": [p["_FireRegVal"], p["_WaterRegVal"], p["_ThunderRegVal"], p["_IceRegVal"], p["_DragonRegVal"]],
            }
            if not p["_CustomTableNo"]:
                continue
            armors[str(aid)] = {
                "names": _names(armor_msgs.get(f"A_{PARTS[kind - 1]}_{aid & 0xFFFF:03}_Name")),
                "table": p["_CustomTableNo"],
                "cost": p["_CustomCost"],
                "skills": [[s, lv] for s, lv in zip(p["_SkillList"], p["_SkillLvList"]) if s],
                "slots": p["_DecorationsNumList"],
                "part": kind - 1,
                "rare": p["_Rare"],
            }

        log("Reading decorations and weapons...")
        deco_msgs = {}
        for suffix in ("", "_MR"):
            deco_msgs.update(_msg_map(pak, f"data/Define/Player/Equip/Decorations/Decorations_Name{suffix}"))
        decorations = []
        for p in rsz.parse_user(pak.read_any(
                "data/Define/Player/Equip/Decorations/DecorationsBaseData.user", ["2"]))[0]["_Param"]:
            did = p["_Id"]
            dskills = [(s, lv) for s, lv in zip(p["_SkillIdList"], p["_SkillLvList"]) if s and lv]
            names = _names(deco_msgs.get(f"{deco_tag(did)}_Name")) if did else {}
            if not did or not dskills or "en" not in names:
                continue
            decorations.append({"id": did, "names": names, "level": p["_DecorationLv"], "rare": p["_Rare"] + 1,
                                "skill": dskills[0][0], "points": dskills[0][1]})
        weapons = {}
        for wtype, cls in enumerate(WEAPON_TYPES):
            wdir = f"data/Define/Player/Weapon/{cls}"
            wmsgs = {}
            for suffix in ("", "_MR"):
                try:
                    wmsgs.update(_msg_map(pak, f"{wdir}/{cls}_Name{suffix}"))
                except Exception:
                    pass
            for p in rsz.parse_user(pak.read_any(f"{wdir}/{cls}BaseData.user", ["2"]))[0]["_Param"]:
                names = _names(wmsgs.get(f"W_{cls}_{p['_Id'] & 0xFFFF:03}_Name"))
                if "en" not in names:
                    continue
                weapons[str(p["_Id"])] = {"names": names, "type": wtype, "rare": p["_RareType"] + 1,
                                         "slots": (_expand(p["_SlotNumList"]) + [0, 0, 0])[:3]}
    finally:
        pak.close()
    return {"version": CACHE_VERSION, "decorations": decorations, "weapons": weapons, "base": base, "armor_lots": armor_lots, "category_lots": category_lots,
            "skill_costs": skill_costs, "skills": skills, "max_levels": max_levels, "skill_colors": skill_colors, "armors": armors,
            "all_armors": all_armors,
            "deco_levels": deco_levels, "talisman_skills": talisman_skills, "melding": melding}


def deco_tag(did: int) -> str:
    """Message tag of a decoration (ids above 108 are the Sunbreak ones, numbered from 200)."""
    return f"Decorations_{did - 1:03}" if did <= 108 else f"Decorations_{did - 109 + 200:04}"


def _expand(num_list) -> list[int]:
    """[n_lv1, n_lv2, n_lv3, n_lv4] -> slot levels, highest first."""
    out = []
    for i in range(len(num_list) - 1, -1, -1):
        out += [i + 1] * num_list[i]
    return out


def _fingerprint(game_dir: Path) -> str:
    return "|".join(f"{p.name}:{p.stat().st_size}:{int(p.stat().st_mtime)}"
                    for p in sorted(Path(game_dir).glob("re_chunk_000.pak*")))


def load(game_dir: Path, cache_dir: Path | None = None, rebuild: bool = False, log=print) -> dict:
    cache_dir = cache_dir or default_cache_dir()
    cache = cache_dir / "gamedata.json"
    fp = _fingerprint(game_dir)
    if cache.exists() and not rebuild:
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("version") == CACHE_VERSION and data.get("fingerprint") == fp:
                return data
        except (OSError, ValueError):
            pass
    data = build(game_dir, log)
    data["fingerprint"] = fp
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def tables(data: dict) -> Tables:
    return Tables(
        base=[Buildup(b["table"], b["id"], b["category"], b["cost"], tuple(b["values"]), tuple(b["lots"]))
              for b in data["base"]],
        armor_lots=[tuple(x) for x in data["armor_lots"]],
        category_lots={int(k): v for k, v in data["category_lots"].items()},
        skill_costs=[tuple(x) for x in data["skill_costs"]],
        max_levels={int(k): v for k, v in data["max_levels"].items()},
    )
