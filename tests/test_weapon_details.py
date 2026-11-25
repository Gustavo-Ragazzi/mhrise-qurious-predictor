from qurious_predictor.weapon_details import attach_tree, sharpness_levels, slot_sharpness_bonuses
from qurious_predictor.weapon_catalog import reference


def test_handicraft_extension_starts_at_highest_base_color_and_crosses_colors():
    base = [50, 50, 50, 50, 40, 0, 0]
    result = sharpness_levels(base, [10, 20, 20, 0])
    assert result["levels"][0] == base
    assert result["levels"][1] == [50, 50, 50, 50, 50, 0, 0]
    assert result["levels"][3] == [50, 50, 50, 50, 50, 20, 0]
    assert result["maximum"] == [50, 50, 50, 50, 50, 20, 20]
    assert result["markers"] == [240, 250, 260, 270, 280, 290]
    assert base == [50, 50, 50, 50, 40, 0, 0]


def test_fixed_sharpness_and_ranged_weapon_have_no_invented_extension():
    base = [50, 30, 120, 80, 70, 20, 30]
    result = sharpness_levels(base, [0, 0, 0, 0])
    assert result["markers"] == [400] * 6
    assert result["maximum"] == base
    assert sharpness_levels([], []) is None


def test_slot_unlock_bonus_shifts_colors_and_reduces_handicraft_needed():
    base, extension = [50, 30, 120, 80, 70, 0, 0], [0, 30, 20, 0]
    original = sharpness_levels(base, extension)
    augmented = sharpness_levels(base, extension, 20)
    assert original["levels"][2][6] == 0
    assert augmented["levels"][2][6] == 10
    assert augmented["maximum"][0] == 30
    assert augmented["maximum"][6] == 40
    assert sum(augmented["maximum"]) == sum(original["maximum"]) == 400
    assert augmented["markers"] == original["markers"]


def test_fixed_maximum_weapon_gains_highest_color_and_can_consume_orange():
    result = sharpness_levels([10, 30, 100, 100, 100, 30, 30], [0, 0, 0, 0], 20)
    assert result["maximum"] == [0, 20, 100, 100, 100, 30, 50]
    assert result["markers"] == [400] * 6
    assert result["levels"][0] == result["maximum"]


def test_slot_bonuses_are_summed_only_for_expansion_ids_in_weapon_table():
    tables = [{"table": 1, "category": 7, "ids": [49, 53, 55, 0]},
              {"table": 1, "category": 5, "ids": [44]}]
    bonuses = [{"table": 1, "id": 53, "categories": [5, 0], "values": [10, 0]},
               {"table": 1, "id": 55, "categories": [1, 5], "values": [10, 10]},
               {"table": 1, "id": 44, "categories": [5], "values": [50]}]
    assert slot_sharpness_bonuses(tables, bonuses) == {1: 20}


def test_tree_links_use_branch_and_index_not_name_or_sort_order():
    weapons = {"1": {}, "2": {}, "3": {}}
    nodes = [{"id": 1, "tree": 1, "index": 0, "prevTree": 0, "prevIndex": -1,
              "nextTrees": [1, 2], "nextIndices": [1, 0], "village": 1, "hub": 0, "master": 0},
             {"id": 2, "tree": 1, "index": 1, "prevTree": 1, "prevIndex": 0,
              "nextTrees": [], "nextIndices": [], "village": 0, "hub": 4, "master": 0},
             {"id": 3, "tree": 2, "index": 0, "prevTree": 1, "prevIndex": 0,
              "nextTrees": [], "nextIndices": [], "village": 0, "hub": 0, "master": 1}]
    attach_tree(weapons, nodes)
    assert weapons["1"]["parent"] is None
    assert weapons["1"]["children"] == ["2", "3"]
    assert weapons["3"]["parent"] == "1"


def test_reference_localizes_materials_categories_and_weapon_specific_levels():
    data = {"weapons": {"1": {"names": {"en": "Test gunlance"}, "type": 6, "rare": 10,
        "slots": [4, 0, 0], "attack": 300, "affinity": 0, "value": 40000,
        "special": {"_GunLanceFireType": 1, "_GunLanceFireLv": 7},
        "upgrade": {"items": [67108865, 67108864], "counts": [7, 0], "category": 154, "categoryPoints": 20}}},
        "weapon_messages": {"I_0001_Name": {"en": "Material"}, "ICT_Name_201": {"en": "MR Bone"}}}
    row = reference(data, lambda names: names["en"])["weapons"][0]
    assert row["special"] == [["Shelling", "Long Lv8"]]
    assert row["upgrade"]["price"] == 40000
    assert row["upgrade"]["materials"] == [{"id": 67108865, "name": "Material", "count": 7}]
    assert row["upgrade"]["category"] == "MR Bone"
    assert row["sharpness"] is None
