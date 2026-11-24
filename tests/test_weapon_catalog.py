from qurious_predictor.weapon_catalog import WEAPON_TYPES, catalog


def test_all_weapon_types_keep_game_enum_order():
    assert len(WEAPON_TYPES) == 14
    assert WEAPON_TYPES[2] == "Hammer"
    assert WEAPON_TYPES[4] == "Long Sword"
    assert WEAPON_TYPES[10] == "Charge Blade"
    assert WEAPON_TYPES[13] == "Bow"


def test_catalog_includes_every_weapon_with_localized_names_and_slots():
    weapons = {str(i): {"type": i, "rare": 10, "slots": [4, 2, 0],
                        "names": {"en": f"Weapon {i}", "pt": f"Arma {i}"}}
               for i in range(14)}
    result = catalog({"weapons": weapons}, lambda names: names["pt"])
    assert len(result["weaponTypes"]) == 14
    assert len(result["weapons"]) == 14
    assert result["weapons"][4] == {"id": "4", "type": 4, "rarity": 10,
                                        "name": "Arma 4", "slots": [4, 2, 0]}
    result["weapons"][4]["slots"][0] = 1
    assert weapons["4"]["slots"] == [4, 2, 0]
