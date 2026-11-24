"""Portable builder requirements, using canonical English names across UI languages."""

import re


HEADER = "# MHRise Qurious skills v1"


def _skills(data):
    return {int(sid): names for sid, names in data["skills"].items()}


def _level(data, sid, level):
    maximum = data["max_levels"].get(str(sid), data["max_levels"].get(sid, 0)) + 1
    if type(level) is not int or not 1 <= level <= maximum:
        raise ValueError(f"Skill #{sid}: level must be between 1 and {maximum}.")


def _weapon(slots):
    if not isinstance(slots, list) or len(slots) != 3 or any(type(v) is not int or not 0 <= v <= 4 for v in slots):
        raise ValueError("Weapon slots must contain three levels between 0 and 4.")
    return slots


def export_skills(data, skills, weapon):
    names = _skills(data)
    lines = [HEADER, "weapon " + " ".join(map(str, _weapon(weapon)))]
    if not skills:
        raise ValueError("Add skills before exporting.")
    for skill in skills:
        sid, level = skill["id"], skill["level"]
        if sid not in names:
            raise ValueError(f"Unknown skill #{sid}.")
        _level(data, sid, level)
        name = names[sid].get("en") or next(iter(names[sid].values()))
        lines.append(f"skill {name} = {level}")
    return "\n".join(lines)


def import_skills(data, text):
    if not isinstance(text, str) or len(text) > 100_000:
        raise ValueError("Paste a skill list of at most 100,000 characters.")
    lookup = {name.strip().casefold(): sid for sid, names in _skills(data).items() for name in names.values()}
    skills, weapon, set_name = {}, None, None
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# Set:"):
            if set_name is not None:
                raise ValueError("Import one named set at a time.")
            set_name = line[len("# Set:"):].strip()
            if not set_name or len(set_name) > 500:
                raise ValueError("The set name must contain between 1 and 500 characters.")
            continue
        if line.startswith("# MHRise Qurious skills") and line != HEADER:
            raise ValueError("Unsupported skill sharing format version.")
        if line.startswith("#"):
            continue
        if line.lower().startswith("weapon "):
            if weapon is not None:
                raise ValueError("Only one weapon slot line is allowed.")
            try:
                weapon = _weapon([int(v) for v in line.split()[1:]])
            except ValueError:
                raise ValueError(f"Line {number}: use weapon 4 2 0 (three slot levels, 0–4).") from None
            continue
        match = re.fullmatch(r"(?:skill\s+)?(.+?)\s*(?:=|\bLv\.?)\s*(\d+)", line, re.IGNORECASE)
        if not match:
            raise ValueError(f"Line {number}: use skill Attack Boost = 7 or Attack Boost Lv7.")
        name, level = match.group(1).strip(), int(match.group(2))
        sid = lookup.get(name.casefold())
        if sid is None:
            raise ValueError(f"Line {number}: unknown skill '{name}'.")
        _level(data, sid, level)
        if sid in skills:
            raise ValueError(f"Line {number}: duplicate skill '{name}'.")
        skills[sid] = level
    if not skills:
        raise ValueError("No skills found. Paste a skill list exported by this app.")
    return {"skills": [{"id": sid, "level": lv} for sid, lv in skills.items()],
            **({"name": set_name} if set_name is not None else {}),
            **({"weapon": weapon} if weapon is not None else {})}
