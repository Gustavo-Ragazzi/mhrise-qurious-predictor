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
    # every piece is rolled on a new copy: one per result kept on it (more if it also takes another's augments)
    copies = {c["id"]: c for c in plan["newCopies"]}
    for s in q["steps"]:
        assert copies[s["id"]]["keep"] >= 1 and copies[s["id"]]["count"] == copies[s["id"]]["keep"] + copies[s["id"]]["burn"]


def test_best_order_many_targets_goes_by_rolls_not_saved_n():
    """More than 6 targets: the next closest from where the plan is, not the ``n`` each set was saved
    with (a set's ``n`` counts from where its own plan was)."""
    from qurious_predictor import planner
    at = {"a": 10, "b": 20, "c": 30, "d": 40, "e": 50, "f": 60, "late": 103, "early": 101}
    # "late" was saved with n 95 by a set planned alone; along the roadmap it comes at 103, after "early"
    ns = {**at, "late": 95}
    targets = [{"id": k, "n": ns[k]} for k in at]

    def find(state, t, limit):
        k = at[t["id"]] - state
        return (k, at[t["id"]]) if 0 < k <= limit else None

    order, gone = planner.best_order(0, targets, find)
    assert gone == []
    assert [t["id"] for t, *_ in order] == ["a", "b", "c", "d", "e", "f", "early", "late"]
    assert sum(k for _, k, _ in order) == 103


def test_results_already_in_the_box_are_done():
    """A saved set's result already in the equipment box (the same piece with the same augment) is
    done: the plan does not look for it again."""
    from qurious_predictor import planner
    from qurious_predictor.savedata import ArmorItem, TalismanItem
    t = {"id": "204472750", "expected": [-7, 1, [0, 0, 2, -7, 0], [[104, -1], [140, 1]]]}
    box = [ArmorItem(204472750, True, -7, [0, 0, 2, -7, 0], 1, [(140, 1), (104, -1)]),
           ArmorItem(205521402, False)]
    rolled = planner.Planner.rolled(box, [TalismanItem([(5, 2), (1, 1)], [2, 1, 0])])
    assert planner.Planner.is_rolled(t, rolled)
    assert not planner.Planner.is_rolled({**t, "id": "205521402"}, rolled)
    assert not planner.Planner.is_rolled({**t, "expected": [-7, 2, [0, 0, 2, -7, 0], [[104, -1], [140, 1]]]}, rolled)
    assert planner.Planner.is_rolled({"skills": [[1, 1], [5, 2]], "slots": [2, 1, 0]}, rolled, True)
    assert not planner.Planner.is_rolled({"skills": [[1, 1], [5, 2]], "slots": [1, 1, 0]}, rolled, True)


def test_best_order_leaves_out_what_does_not_come_again():
    """A result that does not come again is reported and left out; the others are still planned."""
    from qurious_predictor import planner
    at = {"a": 10, "b": 30, "c": 20}
    targets = [{"id": k, "n": 1} for k in ("a", "b", "c", "gone")]

    def find(state, t, limit):
        if t["id"] == "gone":
            return None
        k = at[t["id"]] - state
        return (k, at[t["id"]]) if 0 < k <= limit else None

    order, gone = planner.best_order(0, targets, find)
    assert [t["id"] for t, *_ in order] == ["a", "c", "b"]
    assert [t["id"] for t in gone] == ["gone"]


def test_borrowed_pieces_are_rolls_of_the_set_too():
    """A piece taken from another saved set's plan is one of this set's rolls: the plan keeps it even
    when that other set changes."""
    from qurious_predictor import planner
    piece = {"part": 0, "id": "1", "name": "Helm", "kind": "planned",
             "planned": {"type": 0, "typeName": "Augment", "n": 285, "cost": 10, "sets": ["Other"]},
             "qurious": {"skills": [{"id": 37, "delta": 1}], "slots": 0, "def": 1, "res": [0, 0, 0, 0, 0]}}
    tal = {"kind": "planned", "method": 11, "n": 12, "targetName": "Wirebug Whisperer", "sets": ["Other"],
           "skills": [{"id": 104, "level": 3}]}
    t = planner.targets_of({"pieces": [piece, None, None, None, None], "talisman": tal,
                            "slots": [[]] * 6 + [[{"lv": 3}, {"lv": 2}]]}, {"Wirebug Whisperer": 104}.get)
    assert t["armor"] == [{"id": "1", "name": "Helm", "part": 0, "type": 0, "cost": 10, "n": 285, "via": None,
                           "expected": [1, 0, [0, 0, 0, 0, 0], [[37, 1]]]}]
    assert t["talismans"] == [{"method": 11, "target": 104, "n": 12, "skills": [[104, 3]], "slots": [3, 2, 0]}]


@needs_game
def test_progress_ticks_off_a_plan_without_planning_again():
    data = gamedata.load(Path(GAME), log=lambda m: None)
    gens = [XorShift128((0x5151 + i, 0x2727 * (i + 1), 0x3939 ^ i, 0x4141)) for i in range(56)]
    nt = search.native_tables(data)
    ty = engine.TYPE_SKILL
    pieces = [(aid, a) for aid, a in data["armors"].items() if a["cost"] == 12]
    (p1, a1), (p2, a2) = pieces[0], pieces[len(pieces) // 2]
    seq = engine.seed_index(12, ty)

    def nth(a, n):
        d, sl, res, sk = search._native.rolls(nt, gens[seq].state(), a["table"], a["cost"],
                                              [tuple(s) for s in a["skills"]], ty, n)[-1]
        return [d, sl, list(res), sorted([s, v] for s, v in sk if v)]

    sets = [{"name": "A", "targets": {"armor": [{"id": p1, "name": p1, "part": a1["part"], "type": ty, "cost": 12, "n": 9,
                                                 "expected": nth(a1, 9)}], "talismans": [], "craft": []}},
            {"name": "B", "targets": {"armor": [{"id": p2, "name": p2, "part": a2["part"], "type": ty, "cost": 12, "n": 25,
                                                 "expected": nth(a2, 25)}], "talismans": [], "craft": []}}]
    pl = planner.Planner(data, melding.Tables(data["melding"]))
    plan = pl.plan(sets, gens, [])
    (q,) = plan["armor"]
    assert len(q["steps"]) == 2

    def walk(k):
        """The generators after the first k augments of the route."""
        g = [XorShift128(x.state()) for x in gens]
        state, left = gens[seq].state(), k
        for s in q["steps"]:
            for aid, n in ([(s["burnOn"], s["augments"] - 1), (s["id"], 1)] if s["burnOn"] and s["augments"] > 1
                           else [(s["id"], s["augments"])]):
                n = min(n, left)
                if n:
                    a = data["armors"][aid]
                    state, _ = search._native.augment_advance(nt, list(state), a["table"], a["cost"],
                                                              [tuple(x) for x in a["skills"]], ty, n)
                left -= n
        g[seq] = XorShift128(state)
        return g

    first = q["steps"][0]["at"]
    p = pl.progress(plan, walk(0))
    assert q["progress"] == {"done": 0, "onRoute": True, "finished": False} and not any(s["done"] for s in q["steps"])
    p = pl.progress(plan, walk(first))
    assert q["steps"][0]["done"] and not q["steps"][1]["done"] and p["progress"]["augmentsDone"] == first
    assert not q["steps"][0]["inBox"]                # rolled, but that result was not put in the box here
    pl.progress(plan, walk(first + 1))
    assert q["steps"][1]["doneHere"] == 1
    pl.progress(plan, walk(q["total"]))
    assert q["progress"]["finished"] and all(s["done"] for s in q["steps"])
    # the sequence somewhere the route never passes (something else augmented on it): off the plan
    g = walk(first)
    g[seq] = XorShift128((1, 2, 3, 4))
    p = pl.progress(plan, g)
    assert p["progress"]["offRoute"] == 1 and not q["progress"]["onRoute"] and not any(s["done"] for s in q["steps"])
