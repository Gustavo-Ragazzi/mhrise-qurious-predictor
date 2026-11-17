"""Set builder and build optimizer (qurious_predictor.builder on native/core/src/sets.rs).

* Always: the decoration message tags.
* With game data (MHR_GAME_DIR) and the compiled engine: every set found reaches the wanted skills with
  the decorations it lists, in slots big enough; future augments and talismans are exactly what the
  engine predicts for that roll; the optimizer front gets better with every step.
"""

import os
from pathlib import Path

import pytest

from qurious_predictor import builder, engine, gamedata, melding, search
from qurious_predictor.rng import XorShift128
from qurious_predictor.savedata import ArmorItem, TalismanItem

GAME = os.environ.get("MHR_GAME_DIR")
needs_game = pytest.mark.skipif(not (GAME and search._native), reason="needs MHR_GAME_DIR and the compiled engine")


def test_deco_tag():
    assert gamedata.deco_tag(1) == "Decorations_000"
    assert gamedata.deco_tag(108) == "Decorations_107"
    assert gamedata.deco_tag(109) == "Decorations_0200"


@pytest.fixture(scope="module")
def data():
    return gamedata.load(Path(GAME), log=lambda m: None)


@pytest.fixture(scope="module")
def build(data):
    return builder.Builder(data, melding.Tables(data["melding"]))


def gens():
    return [XorShift128((0x1234567 + 77 * i, 0x89ABCDE ^ i, 0x2468ACE + 13 * i, 0x13579BD)) for i in range(56)]


def skill(data, name):
    return next(int(k) for k, v in data["skills"].items() if v.get("en") == name)


def check_set(data, f, reqs, weapon, owned_decos=None):
    """Recompute the set's skills from its pieces and decorations; every decoration fits its slot."""
    decos = {d["id"]: d for d in data["decorations"]}
    slots = [list(weapon)] + [p["slots"] if p else [0, 0, 0] for p in f.pieces] + [f.talisman["slots"] if f.talisman else [0, 0, 0]]
    slots = [[lv for lv in s if lv] for s in slots]
    totals = {}
    for p in [*f.pieces, f.talisman]:
        for s, lv in (p["skills"] if p else []):
            totals[s] = totals.get(s, 0) + lv
    used = {}
    taken = set()
    for owner, k, did, _extra in f.decos:
        d = decos[did]
        assert (owner, k) not in taken
        taken.add((owner, k))
        assert d["level"] <= slots[owner][k], "decoration in a slot too small"
        totals[d["skill"]] = totals.get(d["skill"], 0) + d["points"]
        used[did] = used.get(did, 0) + 1
    if owned_decos is not None:
        assert all(n <= owned_decos.get(did, 0) for did, n in used.items())
    for s, lv in reqs:
        assert totals.get(s, 0) >= lv, (data["skills"][str(s)]["en"], totals.get(s, 0), lv)


@needs_game
def test_gamedata_for_sets(data):
    assert len(data["decorations"]) > 200 and len(data["weapons"]) > 3000
    assert all(a["defMax"] >= a["def"] for a in data["all_armors"].values())
    assert {d["level"] for d in data["decorations"]} == {1, 2, 3, 4}


@needs_game
def test_sets_reach_the_skills(data, build):
    reqs = [(skill(data, n), lv) for n, lv in [("Attack Boost", 7), ("Weakness Exploit", 3), ("Critical Eye", 5),
                                               ("Critical Boost", 3)]]
    o = builder.Options(reqs=reqs, weapon=[3, 1, 0], limit=5)
    found, counts = build.search(o)
    assert counts["complete"] and found
    assert all(f.cost == 0 for f in found)          # game armor alone: no rolls
    for f in found:
        check_set(data, f, reqs, o.weapon)
    assert [f.defense for f in found] == sorted((f.defense for f in found), reverse=True)


@needs_game
def test_owned_decorations_are_counted(data, build):
    reqs = [(skill(data, "Attack Boost"), 7), (skill(data, "Critical Eye"), 7)]
    few = {d["id"]: 1 for d in data["decorations"]}
    o = builder.Options(reqs=reqs, weapon=[4, 4, 4], owned_decos=True, limit=3)
    found, _ = build.search(o, owned_decos=few)
    for f in found:
        check_set(data, f, reqs, o.weapon, few)


@needs_game
def test_rolled_pieces_are_the_predicted_augments(data, build):
    g = gens()
    reqs = [(skill(data, n), lv) for n, lv in [("Attack Boost", 7), ("Weakness Exploit", 3), ("Critical Eye", 7),
                                               ("Critical Boost", 3), ("Agitator", 5), ("Burst", 3)]]
    o = builder.Options(reqs=reqs, weapon=[1, 0, 0], game_armor=True, qurious_rolls=200, talisman_rolls=200, limit=5)
    found, counts = build.search(o, generators=g)
    assert found
    tables = search.native_tables(data)
    for f in found:
        check_set(data, f, reqs, o.weapon)
        for p in f.pieces:
            if not p or p["kind"] != "roll":
                continue
            a = data["armors"][p["id"]]
            s = search._native.rolls(tables, g[engine.seed_index(a["cost"], p["type"])].state(), a["table"], a["cost"],
                                     [tuple(x) for x in a["skills"]], p["type"], p["n"])[-1]
            levels = {sid: lv for sid, lv in a["skills"]}
            for sid, v in s[3]:
                levels[sid] = levels.get(sid, 0) + v
            assert sorted(p["skills"]) == sorted((k, v) for k, v in levels.items() if v > 0)
        t = f.talisman
        if t and t["kind"] == "roll":
            row = next(r for r in build.meld.targets(t["method"]) if r.skill == t["target"]) if t["target"] else None
            m = melding.Melder(build.meld, t["method"], t["target"])
            rng = XorShift128(g[melding.generator_index(t["method"], row)].state())
            got = [m.talisman(rng, n) for n in range(1, t["n"] + 1)][-1]
            assert [list(x) for x in got.skills] == [list(x) for x in t["skills"]] and list(got.slots) == t["slots"]
    # the closest set needs no more rolls than any other found
    assert found[0].cost == min(f.cost for f in found)


@needs_game
def test_optimizer_front(data, build):
    names = ["Attack Boost", "Critical Eye", "Weakness Exploit"]
    reqs = [(skill(data, n), 2) for n in names]
    # a box with a few plain master rank pieces of each part and one talisman
    by_part = {}
    for aid, a in data["armors"].items():
        if a["rare"] + 1 >= 8 and len(by_part.setdefault(a["part"], [])) < 6:
            by_part[a["part"]].append(int(aid))
    box = [ArmorItem(aid, False, resistances=[0] * 5, skills=[], index=i)
           for i, aid in enumerate(x for p in sorted(by_part) for x in by_part[p])]
    tal = TalismanItem([(reqs[0][0], 2), (reqs[1][0], 2)], [2, 1, 0], index=900)
    weights = {s: 10.0 for s, _ in reqs}
    o = builder.Options(reqs=reqs, weapon=[4, 4, 4], game_armor=False, qurious_rolls=100, talisman_rolls=100,
                        value="score", cost_first=False, weights=weights, slot_values=[0, 7, 15, 24, 36], limit=6)
    start = ([next(it for it in box if data["all_armors"][str(it.armor_id)]["part"] == p) for p in range(5)], tal)
    front, counts = build.best_and_improve(o, start, box, [tal], gens(), {})
    assert front
    for a, b in zip(front, front[1:]):
        assert a.cost < b.cost and a.score < b.score
    for f in front:
        check_set(data, f, reqs, o.weapon)


@needs_game
def test_excluded_pieces_and_avoided_skills(data, build):
    reqs = [(skill(data, n), lv) for n, lv in [("Attack Boost", 7), ("Weakness Exploit", 3), ("Critical Eye", 5)]]
    first, _ = build.search(builder.Options(reqs=reqs, weapon=[3, 1, 0], limit=3))
    banned = {p["id"] for p in first[0].pieces if p}
    avoid = frozenset({skill(data, "Dragonheart"), skill(data, "Critical Boost")})
    found, _ = build.search(builder.Options(reqs=reqs, weapon=[3, 1, 0], limit=5, exclude_armor=frozenset(banned),
                                            avoid_skills=avoid))
    assert found
    for f in found:
        check_set(data, f, reqs, [3, 1, 0])
        assert not banned & {p["id"] for p in f.pieces if p}
        assert not avoid & {s for s, _ in f.skills}
