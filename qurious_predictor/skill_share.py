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


def export_skills(data, skills, weapon, bonuses=None, weapon_id=None):
    names = _skills(data)
    selected = None
    if weapon_id is not None:
        selected = data.get("weapons", {}).get(str(weapon_id))
        if selected is None:
            raise ValueError("Selected weapon was not found in the game data.")
        weapon = list(selected["slots"])
    lines = [HEADER, "weapon " + " ".join(map(str, _weapon(weapon)))]
    if selected:
        from .weapon_catalog import WEAPON_TYPES
        name = selected["names"].get("en") or next(iter(selected["names"].values()))
        lines.extend([f"# Weapon ID: {weapon_id}", f"# Weapon type: {WEAPON_TYPES[selected['type']]}",
                      f"# Weapon name: {name}"])
    if not skills:
        raise ValueError("Add skills before exporting.")
    lines.append("# Required skills")
    for skill, bonus in [(skill, False) for skill in skills] + [(skill, True) for skill in bonuses or []]:
        sid, level = skill["id"], skill["level"]
        if sid not in names:
            raise ValueError(f"Unknown skill #{sid}.")
        _level(data, sid, level)
        name = names[sid].get("en") or next(iter(names[sid].values()))
        if bonus and not any(line.startswith("bonus ") for line in lines):
            lines.append("# Bonus skills (extra levels, reference only)")
        lines.append(f"{'bonus' if bonus else 'skill'} {name} = {level}")
    return "\n".join(lines)


def import_skills(data, text):
    if not isinstance(text, str) or len(text) > 100_000:
        raise ValueError("Paste a skill list of at most 100,000 characters.")
    lookup = {name.strip().casefold(): sid for sid, names in _skills(data).items() for name in names.values()}
    skills, bonuses, weapon, set_name = {}, {}, None, None
    weapon_details = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip().lstrip("\ufeff")
        if not line:
            continue
        metadata = line[1:].lstrip() if line.startswith("#") else line
        field, separator, value = metadata.partition(":")
        if separator and field.casefold() in ("weapon id", "weapon type", "weapon name"):
            field = field.casefold()
            if field in weapon_details or not value.strip():
                raise ValueError(f"Line {number}: invalid or duplicate weapon details.")
            weapon_details[field] = value.strip()
            continue
        if metadata.casefold().startswith("set:"):
            if set_name is not None:
                raise ValueError("Import one named set at a time.")
            set_name = metadata[len("Set:"):].strip()
            if not set_name or len(set_name) > 500:
                raise ValueError("The set name must contain between 1 and 500 characters.")
            continue
        if metadata.casefold().startswith("mhrise qurious skills"):
            if metadata.casefold() != HEADER[2:].casefold():
                raise ValueError("Unsupported skill sharing format version.")
            continue
        if metadata.casefold() in ("required skills", "bonus skills (extra levels, reference only)"):
            continue
        bonus_line = metadata.casefold().startswith("bonus ")
        if bonus_line:
            line = metadata[len("bonus "):]
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
        target = bonuses if bonus_line else skills
        if sid in target:
            raise ValueError(f"Line {number}: duplicate skill '{name}'.")
        target[sid] = level
    if not skills:
        raise ValueError("No skills found. Paste a skill list exported by this app.")
    selected_fields = {}
    if weapon_details:
        weapon_id = weapon_details.get("weapon id")
        selected = data.get("weapons", {}).get(weapon_id)
        if selected is None:
            raise ValueError("Shared weapon was not found. Update the game data or share with manual slots.")
        slots = _weapon(list(selected["slots"]))
        if weapon is not None and weapon != slots:
            raise ValueError("Shared slots do not match the selected weapon. Export the set again.")
        weapon = slots
        selected_fields = {"weaponId": weapon_id, "weaponType": selected["type"]}
    return {"skills": [{"id": sid, "level": lv} for sid, lv in skills.items()],
            **selected_fields,
            **({"bonuses": [{"id": sid, "level": lv} for sid, lv in bonuses.items()]} if bonuses else {}),
            **({"name": set_name} if set_name is not None else {}),
            **({"weapon": weapon} if weapon is not None else {})}
