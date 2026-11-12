"""Static tables read from the user's own game install, cached as JSON (nothing from Capcom ships)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from mhrise_exporter import rsz
from mhrise_exporter.gamedata import PARTS, _msg_map, _names, skill_msg_tag
from mhrise_exporter.pak import open_game_paks

from .engine import Buildup, Tables

CACHE_VERSION = 4
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
})
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
        armors = {}
        for p in rsz.parse_user(pak.read_any("data/Define/Player/Armor/ArmorBaseData.user", ["2"]))[0]["_Param"]:
            aid = p["_Id"]
            kind = (aid >> 20) & 0xF
            if not p["_IsValid"] or not 1 <= kind <= 5 or not p["_CustomTableNo"]:
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
    finally:
        pak.close()
    return {"version": CACHE_VERSION, "base": base, "armor_lots": armor_lots, "category_lots": category_lots,
            "skill_costs": skill_costs, "skills": skills, "max_levels": max_levels, "skill_colors": skill_colors, "armors": armors}


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
