import pytest

from qurious_predictor.skill_share import export_skills, import_skills


DATA = {"skills": {"1": {"en": "Attack Boost", "pt-br": "Aumento de Ataque"},
                   "2": {"en": "Critical Eye"}}, "max_levels": {"1": 6, "2": 6}}


def test_cross_language_round_trip_with_weapon_slots():
    payload = {"skills": [{"id": 1, "level": 7}, {"id": 2, "level": 4}], "weapon": [4, 2, 0]}
    text = export_skills(DATA, **payload)
    assert "skill Attack Boost = 7" in text
    assert import_skills(DATA, text) == payload


def test_manual_localized_list_preserves_unspecified_weapon():
    assert import_skills(DATA, "Aumento de Ataque Lv7\ncritical eye = 3") == {
        "skills": [{"id": 1, "level": 7}, {"id": 2, "level": 3}]}


@pytest.mark.parametrize("text", ["", "# comments", "Unknown Lv2", "Attack Boost Lv8",
    "Attack Boost Lv0", "Attack Boost = 7\nAttack Boost Lv3", "Attack Boost = 7\ninvalid",
    "weapon 5 0 0\nAttack Boost Lv7", "weapon 4 0\nAttack Boost Lv7",
    "weapon 4 0 0\nweapon 2 0 0\nAttack Boost Lv7", "# MHRise Qurious skills v2\nAttack Boost Lv7"])
def test_invalid_import_rejected_as_a_whole(text):
    with pytest.raises(ValueError):
        import_skills(DATA, text)


def test_invalid_export_rejected():
    with pytest.raises(ValueError):
        export_skills(DATA, [{"id": 1, "level": 8}], [0, 0, 0])
    with pytest.raises(ValueError):
        export_skills(DATA, [], [0, 0, 0])


def test_saved_set_export_preserves_name_and_final_skills_without_mutation():
    from types import SimpleNamespace
    from qurious_predictor.app_sets import SetsMixin
    entry = {"id": 4, "name": "Meu set: Espadão", "query": {"skills": [{"id": 1, "level": 3}], "weapon": [4, 2, 0]},
             "set": {"skills": [{"id": 1, "level": 7}, {"id": 2, "level": 4}]}}
    app = SimpleNamespace(data=DATA, saved_sets=lambda: [entry])
    result = SetsMixin.saved_set_skills_export(app, 4)
    assert result["text"].startswith("# Set: Meu set: Espadão\n")
    assert import_skills(DATA, result["text"]) == {
        "skills": entry["query"]["skills"], "weapon": [4, 2, 0], "name": entry["name"],
        "bonuses": [{"id": 1, "level": 4}, {"id": 2, "level": 4}]}
    assert entry["query"]["skills"][0]["level"] == 3
    assert "error" in SetsMixin.saved_set_skills_export(app, 999)


def test_saved_set_export_legacy_weapon_slots_and_requirements_fallback():
    from types import SimpleNamespace
    from qurious_predictor.app_sets import SetsMixin
    entry = {"id": 1, "name": "Old set", "query": {"skills": [{"id": 1, "level": 7}]},
             "set": {"slots": {"0": [{"lv": 3}]}}}
    app = SimpleNamespace(data=DATA, saved_sets=lambda: [entry])
    result = SetsMixin.saved_set_skills_export(app, 1)
    assert import_skills(DATA, result["text"])["weapon"] == [3, 0, 0]


def test_import_named_set_and_reject_multiple_sets():
    result = import_skills(DATA, "# Set: Meu set de Espadão\nAttack Boost Lv7")
    assert result["name"] == "Meu set de Espadão"
    with pytest.raises(ValueError, match="one named set"):
        import_skills(DATA, "# Set: One\nAttack Boost Lv7\n# Set: Two\nCritical Eye Lv4")


@pytest.mark.parametrize("prefix", ["", "# "])
def test_import_metadata_with_or_without_comment_markers(prefix):
    text = f"\ufeff{prefix}Set: DragonHearth Build\n{prefix}MHRise Qurious skills v1\nweapon 4 2 0\nskill Attack Boost = 7"
    assert import_skills(DATA, text) == {
        "name": "DragonHearth Build", "weapon": [4, 2, 0], "skills": [{"id": 1, "level": 7}]}


def test_plain_metadata_still_rejects_unsupported_versions_and_multiple_sets():
    with pytest.raises(ValueError, match="version"):
        import_skills(DATA, "MHRise Qurious skills v2\nAttack Boost Lv7")
    with pytest.raises(ValueError, match="one named set"):
        import_skills(DATA, "Set: One\nAttack Boost Lv7\n# Set: Two\nCritical Eye Lv4")


@pytest.mark.parametrize("strip_comments", [False, True])
def test_bonus_skills_never_become_search_requirements(strip_comments):
    chosen = [{"id": 1, "level": 3}]
    bonuses = [{"id": 1, "level": 4}, {"id": 2, "level": 2}]
    text = export_skills(DATA, chosen, [4, 0, 0], bonuses)
    if strip_comments:
        text = text.replace("# ", "")
    result = import_skills(DATA, text)
    assert result["skills"] == chosen
    assert result["bonuses"] == bonuses
