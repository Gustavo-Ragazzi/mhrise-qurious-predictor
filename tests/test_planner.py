"""Qurious and talisman planner (qurious_predictor.planner).

* Always: a Set builder row turns into the rolls it needs.
* With game data (MHR_GAME_DIR) and the compiled engine: two augments wanted on one sequence are both
  found, in the order that needs the fewest augments, and walking the plan really gives them.
"""

import os
from pathlib import Path

import pytest

from qurious_predictor import engine, gamedata, melding, planner, search
from qurious_predictor.rng import XorShift128

GAME = os.environ.get("MHR_GAME_DIR")
needs_game = pytest.mark.skipif(not (GAME and search._native), reason="needs MHR_GAME_DIR and the compiled engine")


def test_targets_of_a_set_row():
    row = {
        "pieces": [
            {"kind": "roll", "id": "1", "name": "A", "part": 0, "roll": {"type": 1, "cost": 12, "n": 7},
             "qurious": {"def": -3, "slots": 0, "res": [0, 1, 0, 0, 0], "skills": [{"id": 9, "delta": 1}, {"id": 4, "delta": -1}]}},
            {"kind": "game", "id": "2", "name": "B", "owned": False},
            {"kind": "owned", "id": "3", "name": "C", "owned": True}, None, None,
        ],
        "talisman": {"kind": "roll", "method": 11, "target": 5, "n": 3, "skills": [{"id": 5, "level": 3}]},
        "slots": [[], [], [], [], [], [], [{"lv": 2}, {"lv": 1}]],
    }
    t = planner.targets_of(row)
    assert t["armor"][0]["expected"] == [-3, 0, [0, 1, 0, 0, 0], [[4, -1], [9, 1]]]
    assert t["craft"] == [{"id": "2", "name": "B"}]
    assert t["talismans"][0]["slots"] == [2, 1, 0]
    assert planner.Planner._mix(250, [160, 80, 40, 20, 10]) == [1, 1, 0, 0, 1]


@needs_game
def test_two_augments_on_one_sequence():
    data = gamedata.load(Path(GAME), log=lambda m: None)
    gens = [XorShift128((0x1111 + i, 0x2222 * (i + 1), 0x3333 ^ i, 0x4444)) for i in range(56)]
    nt = search.native_tables(data)
    ty = engine.TYPE_SKILL
    pieces = [(aid, a) for aid, a in data["armors"].items() if a["cost"] == 12]
    (p1, a1), (p2, a2) = pieces[0], pieces[len(pieces) // 2]
    seq = engine.seed_index(12, ty)

    def nth(a, n):
        d, sl, res, sk = search._native.rolls(nt, gens[seq].state(), a["table"], a["cost"],
                                              [tuple(s) for s in a["skills"]], ty, n)[-1]
        tot = {}
        for s, v in sk:
            tot[s] = tot.get(s, 0) + v
        return [d, sl, list(res), sorted([s, v] for s, v in tot.items() if v)]

    def target(aid, a, n):
        return {"id": aid, "name": aid, "part": a["part"], "type": ty, "cost": 12, "n": n, "expected": nth(a, n)}

    sets = [{"name": "A", "targets": {"armor": [target(p1, a1, 30)], "talismans": [], "craft": []}},
            {"name": "B", "targets": {"armor": [target(p2, a2, 20)], "talismans": [], "craft": []}}]
    plan = planner.Planner(data, melding.Tables(data["melding"])).plan(sets, gens, [])
    assert not plan["missing"]["armor"]
    (q,) = plan["armor"]
    assert [s["sets"] for s in q["steps"]] == [["B"], ["A"]]       # the one needed earlier first
    assert q["total"] == q["steps"][-1]["at"] < 50
    # walking the plan with those pieces gives both augments
    state = gens[seq].state()
    for s in q["steps"]:
        a = data["armors"][s["id"]]
        state, last = search._native.augment_advance(nt, list(state), a["table"], a["cost"],
                                                     [tuple(x) for x in a["skills"]], ty, s["augments"])
        assert planner.outcome_key(last) == planner.outcome_key(s["expected"])
    assert plan["totals"]["augments"] == q["total"] and plan["totals"]["zenny"] > 0
    assert plan["materials"]["amber"][0]["count"] * plan["materials"]["amber"][0]["worth"] >= plan["totals"]["amber"]
