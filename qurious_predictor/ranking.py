"""Augment ranking: presets of skill weights, how hard each skill is to get, and roll scores.

A preset gives every skill a weight per level (0 = useless), a weight for each slot level step and a
weight per point of defense. A roll's score is the value of the piece *after* the augment: its skills
(base levels plus/minus the augment, capped at the skill's max) times their weights, plus its slots.
Losing a skill the piece had costs its weight, exactly like gaining one adds it. ``gain`` is the score
minus the piece's score before the augment.

The built-in presets weight a skill by how hard it is to get elsewhere (``TIERS``):
armor-only skills are the most valuable to keep, then skills without a decoration, then skills by
the level of their decoration.
"""

from __future__ import annotations

import re

from mhrise_exporter.export import _expand_slots, apply_slot_bonus

# (tier id, label, default weight per skill level)
TIERS = [
    ("armor", "Armor only", 15.0),           # no decoration, talisman or qurious (Blood Awakening)
    ("talisman", "Talisman, no deco", 14.0),  # also on talismans (Dereliction)
    ("qurious", "Qurious, no deco", 13.5),    # qurious can add it, no decoration (Mail of Hellfire)
    ("deco4", "Deco Lv4", 13.0),              # Bloodlust
    ("deco3", "Deco Lv3", 11.0),              # Blood Rite
    ("deco2", "Deco Lv2", 10.0),              # Weakness Exploit
    ("deco1", "Deco Lv1", 6.0),
]
TIER_WEIGHT = {t: w for t, _, w in TIERS}
# Weight of each slot step: new Lv1 slot, Lv1 -> 2, Lv2 -> 3, Lv3 -> 4.
DEFAULT_SLOT_WEIGHTS = [7.0, 8.0, 9.0, 12.0]

_DAMAGE = [
    "Attack Boost", "Agitator", "Peak Performance", "Resentment", "Resuscitate", "Critical Eye", "Critical Boost",
    "Weakness Exploit", "Latent Power", "Maximum Might", "Burst", "Coalescence", "Bloodlust", "Dereliction",
    "Mail of Hellfire", "Strife", "Berserk", "Dragonheart", "Blood Rite", "Blood Awakening", "Heaven-Sent",
    "Foray", "Sneak Attack", "Adrenaline Rush", "Counterstrike", "Offensive Guard", "Embolden", "Intrepid Heart",
    "Kushala Blessing", "Defiance", "Hellfire Cloak", "Powder Mantle", "Frostcraft",
]
_ELEMENT = [  # boost element only (left out of the raw preset)
    "Critical Element", "Fire Attack", "Water Attack", "Ice Attack", "Thunder Attack", "Dragon Attack",
    "Element Exploit", "Dragon Conversion", "Teostra Blessing",
]
_WIREBUG = ["Wirebug Whisperer", "Wind Mantle", "Frenzied Bloodlust", "Redirection", "Shock Absorber"]
_WEAPON = [
    "Focus", "Rapid Morph", "Artillery", "Load Shells", "Guard", "Guard Up", "Spare Shot", "Normal/Rapid Up",
    "Pierce Up", "Spread Up", "Ammo Up", "Recoil Down", "Reload Speed", "Steadiness", "Rapid Fire Up",
    "Ballistics", "Special Ammo Boost", "Bow Charge Plus", "Horn Maestro", "Inspiration", "Charge Master",
    "Tune-Up", "Bladescale Hone", "Master's Touch", "Razor Sharp", "Handicraft", "Protective Polish",
    "Power Prolonger", "Partbreaker", "Constitution", "Stamina Surge",
]
BUILTIN = [
    ("builtin:meta", "Speedrun meta (all weapons)", _DAMAGE + _ELEMENT + _WIREBUG + _WEAPON),
    ("builtin:raw", "Speedrun meta, raw (no element skills)", _DAMAGE + _WIREBUG + _WEAPON),
]


def tier(data: dict, sid: int) -> str:
    deco = data.get("deco_levels", {}).get(str(sid))
    if deco:
        return f"deco{min(max(int(deco), 1), 4)}"
    if any(s == sid for s, _ in data["skill_costs"]):
        return "qurious"
    if sid in set(data.get("talisman_skills", [])):
        return "talisman"
    return "armor"


def skill_ids_by_name(data: dict) -> dict[str, int]:
    """Lower-case skill name in every game language (and '#id') -> skill id."""
    out = {}
    for sid, names in data["skills"].items():
        out[f"#{sid}"] = int(sid)
        for n in names.values():
            out.setdefault(n.strip().lower(), int(sid))
    return out


def builtin_presets(data: dict) -> list[dict]:
    ids = skill_ids_by_name(data)
    out = []
    for pid, name, skills in BUILTIN:
        weights = {}
        for n in skills:
            sid = ids.get(n.lower())
            if sid is not None:
                weights[str(sid)] = TIER_WEIGHT[tier(data, sid)]
        out.append({"id": pid, "name": name, "builtin": True, "weights": weights,
                    "slots": list(DEFAULT_SLOT_WEIGHTS), "defense": 0.0})
    return out


def empty_preset(pid: str, name: str) -> dict:
    return {"id": pid, "name": name, "builtin": False, "weights": {}, "slots": [0.0, 0.0, 0.0, 0.0], "defense": 0.0}


# ---- text import / export ----------------------------------------------------------------------

HEADER = "# MH Rise Qurious Predictor preset"


def _num(v: float) -> str:
    return f"{v:g}"


def export_text(preset: dict, data: dict) -> str:
    lines = [HEADER, f"name = {preset['name']}"]
    for key, v in zip(("new", "1to2", "2to3", "3to4"), preset["slots"]):
        lines.append(f"slot {key} = {_num(v)}")
    lines.append(f"defense = {_num(preset.get('defense', 0))}")
    names = {int(k): v.get("en") or next(iter(v.values())) for k, v in data["skills"].items()}
    for sid, w in sorted(((int(k), w) for k, w in preset["weights"].items() if w),
                         key=lambda x: (-x[1], names.get(x[0], ""))):
        lines.append(f"skill {names.get(sid, f'#{sid}')} = {_num(w)}")
    return "\n".join(lines) + "\n"


def import_text(text: str, data: dict) -> tuple[dict, list[str]]:
    """Parse ``export_text`` output. Returns (preset without id, unknown lines)."""
    ids = skill_ids_by_name(data)
    preset = {"name": "Imported preset", "builtin": False, "weights": {}, "slots": [0.0] * 4, "defense": 0.0}
    unknown = []
    slot_keys = {"new": 0, "1to2": 1, "2to3": 2, "3to4": 3}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(name|defense|slot\s+(\S+)|skill\s+(.+?))\s*[=:]\s*(.*)$", line, re.I)
        if not m:
            unknown.append(raw)
            continue
        key, value = m.group(1).lower(), m.group(4).strip()
        if key == "name":
            preset["name"] = value or preset["name"]
            continue
        try:
            num = float(value.replace(",", "."))
        except ValueError:
            unknown.append(raw)
            continue
        if key == "defense":
            preset["defense"] = num
        elif key.startswith("slot") and m.group(2).lower() in slot_keys:
            preset["slots"][slot_keys[m.group(2).lower()]] = num
        elif key.startswith("skill") and m.group(3).strip().lower() in ids:
            preset["weights"][str(ids[m.group(3).strip().lower()])] = num
        else:
            unknown.append(raw)
    return preset, unknown


# ---- scoring ------------------------------------------------------------------------------------

class Scorer:
    """Scores the piece after an augment for one preset (runs inside the search workers)."""

    def __init__(self, armor: dict, preset: dict, max_levels: dict[int, int]):
        self.w = {int(k): float(v) for k, v in preset["weights"].items() if float(v)}
        steps = [float(x) for x in preset["slots"]]
        self.slot_value = [0.0, steps[0], steps[0] + steps[1], steps[0] + steps[1] + steps[2], sum(steps)]
        self.def_w = float(preset.get("defense") or 0)
        self.base_lv = {s: lv for s, lv in armor["skills"]}
        self.base_slots = _expand_slots(armor["slots"])
        self.max = {s: max_levels.get(s, 99) + 1 for s in set(self.w) | set(self.base_lv)}
        self.base = self._skills(self.base_lv) + self._slots(self.base_slots)

    def _skills(self, levels: dict[int, int]) -> float:
        return sum(w * min(max(levels.get(s, 0), 0), self.max.get(s, 99)) for s, w in self.w.items())

    def _slots(self, slots: list[int]) -> float:
        return sum(self.slot_value[min(max(lv, 0), 4)] for lv in slots)

    def score(self, s) -> tuple[float, float]:
        """(score of the piece after the augment, gain over the piece before it)."""
        levels = dict(self.base_lv)
        for sid, v in s.skills:
            levels[sid] = levels.get(sid, 0) + v
        total = self._skills(levels) + self.def_w * s.defense
        total += self._slots(apply_slot_bonus(self.base_slots, s.slots) if s.slots else self.base_slots)
        return round(total, 3), round(total - self.base, 3)
