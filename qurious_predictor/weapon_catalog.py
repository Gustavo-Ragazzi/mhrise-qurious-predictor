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
