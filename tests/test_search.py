"""Filter matching rules (run anywhere: no game data needed)."""

from qurious_predictor import engine, search
from qurious_predictor.engine import Buildup, Summary, Tables

ARMOR = {"skills": [[10, 1]], "slots": [0, 1, 0, 0], "table": 1, "cost": 10}
MOH, FB, OTHER = 20, 30, 40


def summary(skills=(), defense=0, slots=0, res=None):
    return Summary(defense=defense, slots=slots, resistances=res or {}, skills=list(skills))


def filters(**kw):
    f = {"skills": [], "slots": [0, 0, 0], "minDef": None, "noSkillLoss": False, "noNegRes": False}
    f.update(kw)
    return f


def test_old_flat_skill_list_becomes_and_groups():
    assert search.skill_groups({"skills": [{"id": 1, "level": 2}, {"id": 3}]}) == [[(1, 2)], [(3, 1)]]


def test_or_group_needs_any_skill():
    ok = search.matcher(ARMOR, filters(skills=[[{"id": MOH, "level": 1}, {"id": FB, "level": 1}]]))
    assert ok(summary([(FB, 1)]))
    assert ok(summary([(MOH, 1)]))
    assert not ok(summary([(OTHER, 1)]))


def test_and_groups_need_all():
    ok = search.matcher(ARMOR, filters(skills=[[{"id": MOH, "level": 1}], [{"id": FB, "level": 1}]]))
    assert not ok(summary([(MOH, 1)]))
    assert ok(summary([(MOH, 1), (FB, 1)]))


def test_level_is_a_minimum_including_the_piece_own_skill():
    ok = search.matcher(ARMOR, filters(skills=[[{"id": 10, "level": 1}]]))
    assert ok(summary())                 # the piece already has it at Lv1
    assert ok(summary([(10, 1)]))        # Lv2 is also >= Lv1
    assert not ok(summary([(10, -1)]))   # lost it


def test_gain_only_needs_the_augment_to_add_the_skill():
    ok = search.matcher(ARMOR, filters(skills=[[{"id": 10, "level": 1}]], gainOnly=True))
    assert not ok(summary())
    assert ok(summary([(10, 1)]))


def test_reachable_skips_stability_and_tables_without_skill_adds():
    tables = Tables(base=[Buildup(1, 1, engine.CAT_SKILL, 3, (1,), (1,))],
                    armor_lots=[(1, engine.CAT_SKILL, 1, 10)], category_lots={}, skill_costs=[(MOH, 3)],
                    max_levels={MOH: 2, 10: 4})
    adds = search.adding_tables(tables)
    assert adds == {1}
    want = filters(skills=[[{"id": MOH, "level": 1}]])
    assert engine.TYPE_STABILITY not in search.reachable(ARMOR, want, tables, adds)
    assert search.reachable({**ARMOR, "table": 2}, want, tables, adds) == []  # table 2 never adds skills
    assert search.reachable(ARMOR, filters(skills=[[{"id": MOH, "level": 4}]]), tables, adds) == []  # above max
    have = filters(skills=[[{"id": 10, "level": 1}]])
    assert engine.TYPE_STABILITY in search.reachable(ARMOR, have, tables, adds)
    assert engine.TYPE_STABILITY not in search.reachable(ARMOR, {**have, "gainOnly": True}, tables, adds)
