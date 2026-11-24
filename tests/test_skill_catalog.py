"""Skill message extraction and localized reference, without a game installation."""

from qurious_predictor import gamedata
from qurious_predictor.skill_catalog import catalog, message_text


def test_extract_base_and_sunbreak_levels(monkeypatch):
    messages = {
        "Explain": {"PlayerSkill_000_Explain": {"en": "Base", "pt": "Base PT"}},
        "Explain_MR": {"PlayerSkill_000_Explain_MR": {"en": "Updated"},
                       "PlayerSkill_200_Explain": {"en": "Sunbreak"}},
        "Detail": {"PlayerSkill_000_00_Detail": {"en": "Attack +5"},
                   "PlayerSkill_000_01_Detail": {"en": "Attack +10"}},
        "Detail_MR": {"PlayerSkill_000_01_Detail_MR": {"en": "Updated +10"},
                      "PlayerSkill_200_00_Detail": {"en": "MR level 1"}},
    }
    monkeypatch.setattr(gamedata, "_msg_map", lambda pak, path: messages[path.split("PlayerSkill_")[1]])
    monkeypatch.setattr(gamedata, "_names", lambda content: content or {})
    result = gamedata.read_skill_details(None, {"1": 1, "112": 0}, {"1": {}, "112": {}})
    assert result["1"]["description"] == {"en": "Updated", "pt": "Base PT"}
    assert result["1"]["levels"] == [{"en": "Attack +5"}, {"en": "Updated +10"}]
    assert result["112"]["levels"] == [{"en": "MR level 1"}]


def test_catalog_localization_max_level_and_missing_text():
    data = {"skills": {"1": {"en": "Resentment", "pt": "Ressentimento"}, "2": {"en": "Alpha"}},
            "max_levels": {"1": 4, "2": 0}, "skill_colors": {"1": 3},
            "skill_details": {"1": {"description": {"en": "While health is red."},
                                      "levels": [{"en": f"Attack +{5 * lv} while active."}
                                                 for lv in range(1, 6)]}}}
    rows = catalog(data, "pt")
    assert [r["id"] for r in rows] == [2, 1]
    skill = rows[1]
    assert skill["name"] == "Ressentimento"
    assert skill["description"] == "While health is red."
    assert skill["max"] == 5 and skill["color"] == 3
    assert skill["levels"][4] == {"level": 5, "effect": "Attack +25 while active.", "values": ""}
    assert rows[0]["levels"] == [{"level": 1, "effect": "", "values": ""}]


def test_game_formatting_is_plain_text():
    assert message_text({"en": '<COLOR FF0000>Attack +5</COLOR><br>Health &amp; stamina'}, "en") == "Attack +5\nHealth & stamina"
    assert message_text({}, "en") == ""


def test_catalog_lists_all_jewel_variants_with_slots_and_skill_points():
    data = {"skills": {"1": {"en": "Example"}, "2": {"en": "No jewel"}},
            "max_levels": {"1": 4, "2": 0}, "skill_colors": {},
            "decorations": [
                {"id": 12, "skill": 1, "names": {"en": "Example Jewel+ 4", "pt-br": "Joia+ 4"}, "level": 4, "points": 2},
                {"id": 11, "skill": 1, "names": {"en": "Example Jewel 2"}, "level": 2, "points": 1},
                {"id": 13, "skill": 3, "names": {"en": "Other"}, "level": 1, "points": 1},
            ]}
    rows = catalog(data, "pt-br")
    assert rows[0]["decorations"] == [
        {"id": 11, "name": "Example Jewel 2", "slot": 2, "points": 1},
        {"id": 12, "name": "Joia+ 4", "slot": 4, "points": 2},
    ]
    assert rows[1]["decorations"] == []
    del data["decorations"]
    assert all(not row["decorations"] for row in catalog(data, "en"))


def test_bloodlust_values_with_existing_cache_and_translated_name():
    # Numeric supplements must work with already-extracted caches: no game-data rebuild needed.
    data = {"skills": {"117": {"en": "Bloodlust", "pt-br": "Sede de Sangue"}},
            "max_levels": {"117": 2}, "skill_colors": {},
            "skill_details": {"117": {"levels": [{"en": "While infected, attack increases."}]}}}
    skill = catalog(data, "en")[0]
    assert skill["levels"][0]["effect"] == "While infected, attack increases."
    assert "attack +10" in skill["levels"][0]["values"]
    assert "affinity +20% for 60s" in skill["levels"][0]["values"]
    assert "attack +15" in skill["levels"][1]["values"]
    assert "affinity +25% for 60s" in skill["levels"][1]["values"]
    assert "attack +20" in skill["levels"][2]["values"]
    assert "affinity +25% for 90s" in skill["levels"][2]["values"]
    assert skill["valuesSource"]["url"].startswith("https://")
    translated = catalog(data, "pt-br")[0]
    assert translated["name"] == "Sede de Sangue"
    assert "ataque +10" in translated["levels"][0]["values"]
    assert "attack +10" in catalog(data, "ja")[0]["levels"][0]["values"]


def test_values_do_not_guess_for_unknown_skills_or_changed_level_caps():
    from qurious_predictor.skill_values import supplement
    assert supplement({"en": "Unknown"}, 3, "en") is None
    assert supplement({"en": "Bloodlust"}, 4, "en") is None


def test_ammo_up_values_reach_the_catalog_in_both_languages():
    data = {"skills": {"48": {"en": "Ammo Up", "pt-br": "Expansão de Munição"}},
            "max_levels": {"48": 2}, "skill_colors": {},
            "skill_details": {"48": {"levels": [{"en": "Expands clip size for some ammo types."}]}}}
    skill = catalog(data, "en")[0]
    levels = skill["levels"]
    assert levels[0]["effect"] == "Expands clip size for some ammo types."
    assert "capacity +1" in levels[0]["values"] and "Tranq" in levels[0]["values"]
    assert "Sticky Lv1" in levels[1]["values"] and "piercing variants" in levels[1]["values"]
    assert "+2 total" in levels[2]["values"] and "Wyvern Ammo unchanged" in levels[2]["values"]
    assert all(level["values"] for level in levels)
    assert skill["valuesSource"]["url"].endswith("/265095")
    translated = catalog(data, "pt-br")[0]
    assert translated["name"] == "Expansão de Munição"
    assert "pente +1" in translated["levels"][0]["values"]


def test_weapon_and_scroll_specific_values():
    from qurious_predictor.skill_values import supplement
    mail = supplement({"en": "Mail of Hellfire"}, 3, "en")["levels"]
    assert "attack +25" in mail[1] and "attack +35" in mail[2]
    assert "element ×1.2" in mail[2] and "resistances −50" in mail[2]
    dereliction = supplement({"en": "Dereliction"}, 3, "en")["levels"]
    assert "7 / 12 / 15" in dereliction[1]
    assert "25 / 30 / 35" in dereliction[2]
    burst = supplement({"en": "Burst"}, 3, "en")["levels"][2]
    assert "Dual Blades +15 / +12" in burst
    assert "Bow +10 / +10" in burst
    assert "bowgun attack +10" in burst


def test_all_supplements_have_matching_translations_and_sources():
    from qurious_predictor.skill_values import VALUES
    for name, values in VALUES.items():
        assert len(values["en"]) == len(values["pt"]), name
        assert 1 <= len(values["en"]) <= 7, name
        assert all(values["en"]) and all(values["pt"]), name
        assert values["source"][1].startswith("https://"), name


def test_complete_review_covers_every_supplement_and_level():
    from scripts.audit_skills import audit
    review = audit()
    assert len(review["skills"]) == 147


def test_gunner_skills_from_report_have_numbers_at_every_level():
    from qurious_predictor.skill_values import supplement
    for name in ("Normal/Rapid Up", "Pierce Up", "Spread Up"):
        levels = supplement({"en": name}, 3, "en")["levels"]
        assert "×1.05 (+5%)" in levels[0], name
        assert "×1.1 (+10%)" in levels[1], name
        assert "×1.2 (+20%)" in levels[2], name
    load = supplement({"en": "Load Shells"}, 2, "en")["levels"]
    assert "×0.9" in load[0] and "×0.8" in load[0]
    assert "capacity +1" in load[1] and "5 phials instead of 3" in load[1]


def test_unverified_references_are_explicit_not_fake_values():
    from qurious_predictor.skill_values import supplement
    for name, maximum in [("Ballistics", 3), ("Speed Eating", 3), ("Good Luck", 3), ("Capture Master", 1)]:
        result = supplement({"en": name}, maximum, "en")
        assert result["status"] == "pending", name
        assert all("not been verified" in text for text in result["levels"]), name


def test_latent_power_activation_duration_and_level_bonuses():
    from qurious_predictor.skill_values import supplement
    levels = supplement({"en": "Latent Power"}, 5, "en")["levels"]
    for row, affinity, stamina in zip(levels, (10, 20, 30, 40, 50), (30, 30, 50, 50, 50)):
        assert f"Affinity +{affinity}%" in row
        assert f"consumption −{stamina}%" in row
        assert "120s" in row and "165s (2m45s)" in row
        assert "attacking shortens" in row


def test_embolden_description_and_guard_evade_equivalence():
    data = {"skills": {"136": {"en": "Embolden", "pt-br": "Instigação"}},
            "max_levels": {"136": 2}, "skill_colors": {},
            "skill_details": {"136": {"description": {"en": "Old incomplete defense-only description."}}}}
    for lang in ("en", "pt-br"):
        skill = catalog(data, lang)[0]
        assert "Old incomplete" not in skill["description"]
        assert "Evade Window Lv5" in skill["description"]
        for row, defense, level in zip(skill["levels"], (10, 20, 40), (1, 3, 5)):
            assert f"+{defense}" in row["values"]
            assert f"Evade Window Lv{level}" in row["values"]
            assert f"Guard Lv{level}" in row["values"]
        assert "guard impact" not in skill["levels"][0]["values"]
