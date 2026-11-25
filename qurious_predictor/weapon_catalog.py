"""Weapon names and slots from the installed game's equipment tables."""

# Same enum order as gamedata.WEAPON_TYPES and the game's weapon IDs.
WEAPON_TYPES = ("Great Sword", "Sword & Shield", "Hammer", "Lance", "Long Sword", "Switch Axe",
                "Gunlance", "Dual Blades", "Hunting Horn", "Insect Glaive", "Charge Blade",
                "Light Bowgun", "Heavy Bowgun", "Bow")


def catalog(data, name):
    return {"weaponTypes": [{"id": i, "name": label} for i, label in enumerate(WEAPON_TYPES)],
            "weapons": sorted([{"id": str(wid), "name": name(weapon["names"]), "type": weapon["type"],
                                "rarity": weapon["rare"], "slots": list(weapon["slots"])}
                               for wid, weapon in data.get("weapons", {}).items()],
                              key=lambda weapon: (weapon["type"], weapon["name"].casefold(), weapon["id"]))}


ELEMENTS = ("None", "Fire", "Water", "Thunder", "Ice", "Dragon", "Poison", "Sleep", "Paralysis", "Blast")
AMMO_NAMES = ("None", "Normal 1", "Normal 2", "Normal 3", "Pierce 1", "Pierce 2", "Pierce 3",
              "Spread 1", "Spread 2", "Spread 3", "Shrapnel 1", "Shrapnel 2", "Shrapnel 3",
              "Sticky 1", "Sticky 2", "Sticky 3", "Cluster 1", "Cluster 2", "Cluster 3", "Poison 1", "Poison 2",
              "Paralysis 1", "Paralysis 2", "Sleep 1", "Sleep 2", "Exhaust 1", "Exhaust 2", "Recover 1", "Recover 2",
              "Demon", "Armor", "Flaming", "Piercing Fire", "Water", "Piercing Water", "Freeze", "Piercing Ice",
              "Thunder", "Piercing Thunder", "Dragon", "Piercing Dragon", "Slicing", "Wyvern", "Tranq")


def reference(data, name):
    """Full weapon reference, independent of the hunter's inventory or save."""
    from .weapon_details import sharpness_levels
    from .skill_catalog import message_text
    messages = data.get("weapon_messages", {})
    def msg(tag):
        return name(messages[tag]) if tag in messages else tag
    def recipe(raw, price):
        if not raw:
            return None
        category = raw.get("category", 0)
        tag = f"ICT_Name_{category:02}" if category < 153 else f"ICT_Name_{category + 47:03}"
        return {"price": price, "materials": [
            {"id": iid, "name": msg(f"I_{iid & 0xFFFF:04}_Name"), "count": count}
            for iid, count in zip(raw["items"], raw["counts"]) if count],
            "category": msg(tag) if raw.get("categoryPoints") else None,
            "categoryPoints": raw.get("categoryPoints", 0), "progress": raw.get("progress", 0)}
    rows = []
    for wid, w in data.get("weapons", {}).items():
        p = w.get("special", {})
        attrs = []
        if "_GunLanceFireType" in p:
            attrs.append(["Shelling", f"{('Normal', 'Long', 'Wide')[p['_GunLanceFireType']]} Lv{p['_GunLanceFireLv'] + 1}"])
        if "_SlashAxeBottleType" in p:
            phial = {1: "Element", 2: "Power", 3: "Poison", 4: "Paralysis", 7: "Exhaust", 8: "Dragon"}.get(p["_SlashAxeBottleType"], "Unknown")
            attrs.append(["Phial", f"{phial} {p['_SlashAxeBottleElementVal'] or ''}".strip()])
        if "_ChargeAxeBottleType" in p:
            attrs.append(["Phial", {1: "Element", 2: "Impact"}.get(p["_ChargeAxeBottleType"], "Unknown")])
        if "_InsectGlaiveInsectLv" in p:
            attrs.append(["Kinsect level", str(p["_InsectGlaiveInsectLv"] + 1)])
        if "_HornMelodyTypeList" in p:
            attrs.extend(["Melody", msg(f"Horn_UniqueParam_{mid:03}_Name")] for mid in p["_HornMelodyTypeList"])
        ammo = []
        if "_BulletEquipFlagList" in p:
            attrs.extend([["Deviation", ("None", "L Mild", "L Severe", "R Mild", "R Severe", "LR Mild", "LR Severe")[p["_Fluctuation"]]],
                          ["Reload (base)", str(p["_Reload"])], ["Recoil (base)", str(p["_Recoil"])],
                          ["Cluster trajectory", ("Arc shot", "Level shot")[p["_KakusanType"]]]])
            if "_HeavyBowgunUniqueBulletType" in p:
                attrs.append(["Special ammo", ("Wyvernsnipe", "Wyvernheart")[p["_HeavyBowgunUniqueBulletType"]]])
            else:
                attrs.append(["Special ammo", "Wyvernblast"])
            flags = {1: "Moving shot", 2: "Moving shot / reload", 3: "Moving shot / auto reload",
                     4: "Moving reload", 5: "Moving reload / auto reload", 6: "Auto reload", 7: "Moving shot / reload / auto reload"}
            for i, equipped in enumerate(p["_BulletEquipFlagList"]):
                if not equipped or i == 0 or i >= len(AMMO_NAMES):
                    continue
                ammo.append({"name": AMMO_NAMES[i], "capacity": p["_BulletNumList"][i],
                             "behavior": flags.get(p["_BulletTypeList"][i], "Stationary"),
                             "rapid": i in p.get("_RapidShotList", [])})
        if "_BowChargeTypeList" in p:
            for i, charge in enumerate(p["_BowChargeTypeList"]):
                shot = "None" if not charge else f"{('Rapid', 'Spread', 'Pierce')[(charge - 1) // 5]} Lv{(charge - 1) % 5 + 1}"
                attrs.append([f"Charge {i + 1}", shot + (" (Bow Charge Plus)" if i > p["_BowDefaultChargeLvLimit"] else "")])
            attrs.append(["Arc shot", ("Recovery", "Affinity", "Brace")[p["_BowCurveType"]]])
            coating_names = ("Close-range", "Power", "Poison", "Paralysis", "Sleep", "Blast", "Exhaust")
            boosted = {1: 0, 2: 2, 3: 3, 4: 4}
            enhanced = {boosted[value] for value in p["_BowBottlePowerUpTypeList"] if value in boosted}
            attrs.append(["Coatings", ", ".join(coating_names[i] + (" (enhanced)" if i in enhanced else "") for i, flag in enumerate(p["_BowBottleEquipFlagList"]) if flag and i < len(coating_names))])
        row = {key: w.get(key) for key in ("attack", "affinity", "chaosAffinity", "defense", "element", "elementValue", "element2", "elementValue2", "buyPrice", "rampageSlots", "progress")}
        row.update(id=str(wid), name=name(w["names"]), type=w["type"], rarity=w["rare"], slots=w["slots"],
                   parent=w.get("parent"), children=w.get("children", []), hasTree="children" in w,
                   sort=w.get("sort", 0), sharpness=sharpness_levels(w.get("sharpness", []), w.get("handicraft", [])),
                   slotSharpnessBonus=w.get("slotSharpnessBonus", 0),
                   augmentedSharpness=sharpness_levels(w.get("sharpness", []), w.get("handicraft", []), w.get("slotSharpnessBonus", 0)),
                   special=attrs, ammo=ammo, forge=recipe(w.get("forge"), w.get("value", 0) * 3 // 2),
                   upgrade=recipe(w.get("upgrade"), w.get("value", 0)),
                   rampageSkills=[msg(f"HyakuryuSkill_{sid:03}_Name") for sid in w.get("rampageSkills", []) if sid],
                   description=name(w["description"]) if w.get("description") else "")
        # Keep formatted game strings out of the DOM; the frontend escapes all labels.
        row["name"] = message_text({"en": row["name"]}, "en")
        rows.append(row)
    return {"types": [{"id": i, "name": label} for i, label in enumerate(WEAPON_TYPES)],
            "elements": list(ELEMENTS), "weapons": sorted(rows, key=lambda row: (row["type"], row["sort"], row["name"]))}
