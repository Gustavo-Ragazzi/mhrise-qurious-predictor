"""The Rust engine (qurious_predictor._native) against the Python reference and the game's own data.

* Synthetic tables (run anywhere): random tables that use every rule, compared roll by roll with
  engine.py, including the generator state afterwards.
* Game data (MHR_GAME_DIR, MHR_QURIOUS_DATA): the recorded in-game traces and the 80,000 bulk
  samples, every armor piece of the game against engine.py, and the searches end to end.
"""

import os
import random
import re
import time
from pathlib import Path

import pytest

from qurious_predictor import engine, gamedata, ranking, search
from qurious_predictor.engine import Buildup, Tables
from qurious_predictor.rng import XorShift128

_native = pytest.importorskip("qurious_predictor._native")

GAME = os.environ.get("MHR_GAME_DIR")
DATA = os.environ.get("MHR_QURIOUS_DATA")
needs_game = pytest.mark.skipif(not GAME, reason="needs MHR_GAME_DIR")
needs_recordings = pytest.mark.skipif(not (GAME and DATA), reason="needs MHR_GAME_DIR and MHR_QURIOUS_DATA")


def _entries(out):
    return [(e.category, e.id, e.value, e.skill, e.cost) for e in out]


def _compare(py_tables, nat_tables, armors, states, types=(0, 1, 2, 3)):
    n = 0
    for a in armors:
        skills = [tuple(x) for x in a["skills"]]
        for st in states:
            for t in types:
                rng = XorShift128(st)
                py = _entries(engine.create_result(rng, py_tables, a["table"], a["cost"], skills, t))
                nat, nat_state = _native.create_result(nat_tables, list(st), a["table"], a["cost"], skills, t)
                assert [tuple(x) for x in nat] == py, (a, st, t)
                assert tuple(nat_state) == rng.state(), (a, st, t)
                n += 1
    return n


# ---- synthetic tables -------------------------------------------------------------------------------

def _synthetic(seed: int):
    """Random tables shaped like the game's: every category, the forced ids, positive/negative/zero costs."""
    r = random.Random(seed)
    base, lots, cat_lots = [], [], {}
    skill_costs = [(s, r.choice([3, 6, 9, 12, 15])) for s in range(1, 40)]
    ids = {engine.CAT_DEF: [1, 2, 3, 4, 61], engine.CAT_RES: [89, 90, 99, 100, 109, 119, 129],
           engine.CAT_RES_PENALTY: [91, 101, 111, 121, 131, 133], engine.CAT_SLOT: [139, 140, 141],
           engine.CAT_SKILL: [146, 147, 148, 149, 150, 151, 152]}
    for table in (1, 2, 3):
        cat_lots[table] = [r.randint(0, 50) for _ in range(4)]
        for cat, bids in ids.items():
            for bid in bids:
                if cat == engine.CAT_SKILL:
                    cost = -r.choice([3, 6]) if bid == 149 else r.choice([3, 6, 9, 12, 15, 4])
                else:
                    cost = r.choice([-6, -3, 0, 2, 3, 4, 6, 9])
                nvals = r.randint(1, 4)
                if cat == engine.CAT_DEF:
                    # Defense values are never 0 in the game: a 0 fill entry would be dropped and
                    # re-added forever (the engines, like the game, would loop).
                    sign = -1 if bid == engine.ID_DEF_PENALTY else 1
                    values = [sign * r.choice([1, 2, 3]) for _ in range(nvals)]
                else:
                    values = [r.choice([-2, -1, 0, 1, 1, 2, 3]) for _ in range(nvals)]
                vlots = [r.choice([0, 0, 1, 5, 10]) for _ in range(nvals)]
                base.append(Buildup(table, bid, cat, cost, tuple(values), tuple(vlots)))
                lots.append((table, cat, bid, r.choice([0, 1, 5, 10, 20])))
    max_levels = {s: r.randint(0, 6) for s in range(1, 40)}
    py = Tables(base, lots, cat_lots, skill_costs, max_levels)
    nat = _native.Tables([(b.table, b.id, b.category, b.cost, list(b.values), list(b.lots)) for b in base],
                         lots, cat_lots, skill_costs, max_levels)
    armors = []
    for table in (1, 2, 3, 7):  # 7: no lots at all
        for _ in range(6):
            k = r.randint(0, 5)
            skills = [[r.randint(1, 39), r.randint(1, 3)] for _ in range(k)]
            armors.append({"table": table, "cost": r.choice([10, 12, 16, 20, 30]), "skills": skills})
    states = [tuple(r.getrandbits(32) for _ in range(4)) for _ in range(60)]
    return py, nat, armors, states


@pytest.mark.parametrize("seed", range(6))
def test_matches_python_on_synthetic_tables(seed):
    py, nat, armors, states = _synthetic(seed)
    assert _compare(py, nat, armors, states) == len(armors) * len(states) * 4


def test_rolls_chain_the_generator():
    py, nat, armors, states = _synthetic(99)
    a = armors[0]
    skills = [tuple(x) for x in a["skills"]]
    rng = XorShift128(states[0])
    want = [engine.summarize(engine.create_result(rng, py, a["table"], a["cost"], skills, 1)) for _ in range(300)]
    got = [search.summary_of(t) for t in _native.rolls(nat, list(states[0]), a["table"], a["cost"], skills, 1, 300)]
    assert got == want


# ---- game data ----------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def gd():
    return gamedata.load(Path(GAME))


def _state(hexstr):
    return [int(hexstr[i:i + 8], 16) for i in range(0, 32, 8)]


@needs_recordings
def test_trace_in_game(gd):
    """The 160 createResult calls traced in game (tests/test_validation.py::test_trace), on Rust."""
    nat = search.native_tables(gd)
    helm = next(a for a in gd["armors"].values() if a["names"].get("en") == "Valstrax Helm - Epoch")
    text = (Path(DATA) / "QuriousTrace.txt").read_text(encoding="utf-8", errors="replace")
    n = 0
    for m in re.finditer(r"^createResult type(\d) i=\d+ pre=(\w{32}) ret=(.*) post=(\w{32})$", text, re.M):
        out, post = _native.create_result(nat, _state(m[2]), helm["table"], helm["cost"],
                                          [tuple(x) for x in helm["skills"]], int(m[1]))
        assert sorted(f"{c}/{i}/v{v}/s{s}/c{k}" for c, i, v, s, k in out) == sorted(m[3].split())
        assert list(post) == _state(m[4])
        n += 1
    assert n == 160


@needs_recordings
def test_bulk_in_game(gd):
    """The 80,000 in-game createResult samples (QuriousBulk.txt), on Rust."""
    path = Path(DATA) / "QuriousBulk.txt"
    if not path.exists():
        pytest.skip("no QuriousBulk.txt")
    nat = search.native_tables(gd)
    lines = path.read_text(encoding="utf-8").splitlines()
    a = gd["armors"][re.search(r" id=(\d+) ", lines[0])[1]]
    skills = [tuple(x) for x in a["skills"]]
    bad = 0
    for ln in lines[1:]:
        _seed, pre, t, *ents = ln.split()
        out, _ = _native.create_result(nat, _state(pre), a["table"], a["cost"], skills, int(t))
        bad += sorted(f"{c}/{i}/{v}/{s}/{k}" for c, i, v, s, k in out) != sorted(ents)
    assert bad == 0 and len(lines) > 80_000


@needs_game
def test_every_armor_piece_matches_python(gd):
    py, nat = gamedata.tables(gd), search.native_tables(gd)
    r = random.Random(7)
    states = [tuple(r.getrandbits(32) for _ in range(4)) for _ in range(8)]
    assert _compare(py, nat, list(gd["armors"].values()), states) == len(gd["armors"]) * 8 * 4


class _Gen:
    def __init__(self, st):
        self.st = st

    def state(self):
        return self.st


def _run(cls, gd, streams, filters, max_matches, limit, rank=None):
    r = random.Random(3)
    gens = [_Gen(tuple(r.getrandbits(32) for _ in range(4))) for _ in range(56)]
    job = cls(gd, gens, streams, filters, max_matches, limit,
              lambda aid, s, n: (s.defense, s.slots, sorted(s.resistances.items()), s.skills), rank=rank)
    while not job.done:
        time.sleep(0.05)
    time.sleep(0.3)  # Python collector thread
    snap = job.snapshot(0)
    return sorted((e["key"], e["n"], str(e["row"]), e.get("score"), e.get("gain")) for e in snap["events"]), snap


@needs_game
def test_searches_match_python(gd):
    ids = list(gd["armors"])[::40]
    streams = [(aid, t) for aid in ids for t in engine.TYPE_NAMES]
    moh = next(int(k) for k, v in gd["skills"].items() if v.get("en") == "Mail of Hellfire")
    filters = {"skills": [[{"id": moh, "level": 1}, {"id": 1, "level": 3}]], "slots": [2, 0, 0], "minDef": -20,
               "noSkillLoss": False, "noNegRes": False}
    want, _ = _run(search.Search, gd, streams, filters, 5, 3000)
    got, snap = _run(search.NativeSearch, gd, streams, filters, 5, 3000)
    assert got == want and snap["done"]
    preset = ranking.builtin_presets(gd)[0]
    want, _ = _run(search.Search, gd, streams, {}, 301, 300, rank={"preset": preset})
    got, _ = _run(search.NativeSearch, gd, streams, {}, 301, 300, rank={"preset": preset})
    # Same best roll per stream (the Python side compares rounded scores, so compare the final best).
    best = lambda ev: {k: (n, s) for k, n, _r, s, _g in ev}  # noqa: E731
    assert best(got) == best(want)
