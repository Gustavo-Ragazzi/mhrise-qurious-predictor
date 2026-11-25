"""Weapon tables and sharpness, read from the installed game (v16 layouts from mhrice)."""


def install_specs(rsz):
    rsz.SPECS["snow.data.CustomBuildupSlotBonusUserData"] = (None, [("_Param", "obj", True)])
    rsz.SPECS["snow.data.CustomBuildupSlotBonusUserData.Param"] = (None, [
        ("table", "u32", False), ("id", "u16", False), ("categories", "u16", True), ("values", "s32", True)])
    rsz.SPECS["snow.data.CustomBuildupWepTableUserData"] = (None, [("_Param", "obj", True)])
    rsz.SPECS["snow.data.CustomBuildupWepTableUserData.Param"] = (None, [
        ("table", "u32", False), ("category", "u16", False), ("ids", "u16", True)])
    rsz.SPECS["snow.data.WeaponChaosCriticalUserData"] = (None, [("_Param", "obj", True)])
    rsz.SPECS["snow.data.WeaponChaosCriticalUserData.Param"] = (None, [("id", "u32", False), ("affinity", "s32", False)])
    craft = [("id", "u32", False), ("itemFlag", "u32", False), ("enemyFlag", "u32", False),
             ("progress", "s32", False), ("items", "u32", True), ("counts", "u32", True),
             ("category", "u32", False), ("categoryPoints", "u32", False)]
    for kind in ("Product", "Process"):
        root = f"snow.data.Weapon{kind}UserData"
        rsz.SPECS[root] = (None, [("_Param", "obj", True)])
        rsz.SPECS[root + ".Param"] = (None, craft + [("output", "u32", True), ("outputCounts", "u32", True)])
    root = "snow.data.WeaponUpdateTreeUserData"
    rsz.SPECS[root] = (None, [("_Param", "obj", True)])
    rsz.SPECS[root + ".Param"] = (None, [
        ("tree", "s32", False), ("index", "s32", False), ("village", "s32", False),
        ("hub", "s32", False), ("master", "s32", False), ("id", "u32", False),
        ("nextTrees", "s32", True), ("nextIndices", "s32", True),
        ("prevTree", "s32", False), ("prevIndex", "s32", False)])


def base_details(p):
    """Keep decoded data; labels/localization are applied when serving the catalog."""
    return {"attack": p["_Atk"], "affinity": p["_CriticalRate"], "defense": p["_DefBonus"],
            "sort": p["_SortId"], "value": p["_BaseVal"], "buyPrice": p["_BuyVal"], "augmentTable": p["_CustomTableNo"],
            "element": p.get("_MainElementType", 0), "elementValue": p.get("_MainElementVal", 0),
            "element2": p.get("_SubElementType", 0), "elementValue2": p.get("_SubElementVal", 0),
            "rampageSlots": [i + 1 for i, count in enumerate(p["_HyakuryuSlotNumList"]) for _ in range(count)],
            "sharpness": p.get("_SharpnessValList", []), "handicraft": p.get("_TakumiValList", []),
            "rampageSkills": p["_HyakuryuSkillIdList"],
            "special": {key: value for key, value in p.items() if key in (
                "_SlashAxeBottleType", "_SlashAxeBottleElementVal", "_GunLanceFireType", "_GunLanceFireLv",
                "_HornMelodyTypeList", "_InsectGlaiveInsectLv", "_ChargeAxeBottleType", "_Fluctuation",
                "_Reload", "_Recoil", "_KakusanType", "_BulletEquipFlagList", "_BulletNumList", "_BulletTypeList",
                "_RapidShotList", "_UniqueBullet", "_HeavyBowgunUniqueBulletType", "_BowBottlePowerUpTypeList",
                "_BowBottleEquipFlagList", "_BowDefaultChargeLvLimit", "_BowChargeTypeList", "_BowCurveType")}}


def attach_tree(weapons, nodes):
    positions = {(node["tree"], node["index"]): str(node["id"]) for node in nodes}
    for node in nodes:
        wid = str(node["id"])
        if wid not in weapons:
            continue
        parent = positions.get((node["prevTree"], node["prevIndex"]))
        children = [positions.get(pair) for pair in zip(node["nextTrees"], node["nextIndices"])]
        weapons[wid].update(parent=parent if parent in weapons and parent != wid else None,
                            children=[child for child in children if child in weapons and child != wid],
                            tree=node["tree"], progress={key: node[key] for key in ("village", "hub", "master")})


def slot_sharpness_bonuses(tables, bonuses):
    """Slot expansion bonuses are incremental, not the sum of selectable augments."""
    rows = {(row["table"], row["id"]): row for row in bonuses}
    result = {}
    for table in tables:
        if table["category"] != 7:
            continue
        total = 0
        for aid in table["ids"]:
            bonus = rows.get((table["table"], aid), {})
            total += sum(value for category, value in zip(bonus.get("categories", []), bonus.get("values", [])) if category == 5)
        result[table["table"]] = total
    return result


def sharpness_levels(base, extension, bonus=0):
    """Takumi entries start at the highest base color; +10 units per Handicraft level."""
    if not base:
        return None
    base = (list(base) + [0] * 7)[:7]
    highest = max((i for i, value in enumerate(base) if value), default=0)
    extension = [(highest + i, max(0, value)) for i, value in enumerate(extension) if highest + i < 7]
    levels = []
    for level in range(6):
        values, remaining = base.copy(), level * 10
        for color, value in extension:
            added = min(value, remaining)
            values[color] += added
            remaining -= added
        levels.append(values)
    if bonus:
        # Augments move units from the lowest colors to the highest possible color.
        # Handicraft still trims the same right-hand 0–50 units from that maximum.
        maximum = levels[5].copy()
        highest = max((i for i, value in enumerate(maximum) if value), default=0)
        remaining = max(0, bonus)
        for color in range(highest):
            taken = min(maximum[color], remaining)
            maximum[color] -= taken
            maximum[highest] += taken
            remaining -= taken
        for i, old in enumerate(levels):
            values, trim = maximum.copy(), sum(maximum) - sum(old)
            for color in range(6, -1, -1):
                taken = min(values[color], trim)
                values[color] -= taken
                trim -= taken
            levels[i] = values
    return {"levels": levels, "maximum": levels[5],
            "markers": [sum(values) for values in levels]}
