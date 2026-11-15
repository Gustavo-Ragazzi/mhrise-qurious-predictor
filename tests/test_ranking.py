"""Ranking presets and scores (run anywhere: no game data needed)."""

from qurious_predictor import ranking
from qurious_predictor.engine import Summary

DATA = {
    "skills": {"1": {"en": "Attack Boost", "ja": "攻撃"}, "113": {"en": "Dereliction"},
               "115": {"en": "Mail of Hellfire"}, "144": {"en": "Blood Awakening"}, "117": {"en": "Bloodlust"}},
    "skill_costs": [[1, 6], [115, 9], [117, 9]],
    "deco_levels": {"1": 2, "117": 4},
    "talisman_skills": [1, 113, 115],
}
ARMOR = {"skills": [[144, 1], [1, 2]], "slots": [0, 1, 0, 0]}  # one Lv2 slot


def test_tiers_follow_how_a_skill_can_be_obtained():
    assert ranking.tier(DATA, 144) == "armor"
    assert ranking.tier(DATA, 113) == "talisman"
    assert ranking.tier(DATA, 115) == "qurious"
    assert ranking.tier(DATA, 117) == "deco4"
    assert ranking.tier(DATA, 1) == "deco2"


def test_score_counts_losses_gains_and_slots():
    preset = {"weights": {"144": 15, "1": 10, "115": 13.5}, "slots": [7, 8, 9, 12], "defense": 0}
    sc = ranking.Scorer(ARMOR, preset, {1: 6, 144: 2, 115: 2})
    assert sc.base == 15 + 20 + 15  # Blood Awakening 1, Attack Boost 2, one Lv2 slot (7 + 8)
    lost = Summary(defense=0, slots=0, resistances={}, skills=[(144, -1), (115, 1)])
    assert sc.score(lost) == (sc.base - 15 + 13.5, -1.5)
    slot = Summary(defense=0, slots=1, resistances={}, skills=[])
    assert sc.score(slot)[1] == 7  # fewer than 3 slots: the point adds a new Lv1 slot


def test_levels_above_the_max_are_not_counted():
    sc = ranking.Scorer({"skills": [[1, 7]], "slots": [0, 0, 0, 0]}, {"weights": {"1": 10}, "slots": [0] * 4}, {1: 6})
    assert sc.score(Summary(defense=0, slots=0, resistances={}, skills=[(1, 1)]))[1] == 0


def test_text_round_trip_and_names_in_any_language():
    preset = {"name": "Mine", "weights": {"1": 10, "115": 13.5}, "slots": [7, 8, 9, 12], "defense": 0.5}
    back, unknown = ranking.import_text(ranking.export_text(preset, DATA), DATA)
    assert unknown == [] and back["name"] == "Mine"
    assert back["weights"] == {"1": 10, "115": 13.5} and back["slots"] == [7, 8, 9, 12] and back["defense"] == 0.5
    jp, _ = ranking.import_text("skill 攻撃 = 3\nskill Nope = 1", DATA)
    assert jp["weights"] == {"1": 3}
