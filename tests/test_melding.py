"""Talisman melding simulation.

* Always: the weighted lot rule and the generator of each method.
* With game data (MHR_GAME_DIR): every method against talismans the game made (tests/data/melding_samples.json,
  recorded with tools/probes/talisman_trace.lua and real melds).
"""

import json
import os
from pathlib import Path

import pytest

from qurious_predictor import gamedata, melding
from qurious_predictor.rng import XorShift128

GAME = os.environ.get("MHR_GAME_DIR")
SAMPLES = Path(__file__).with_name("data") / "melding_samples.json"


def test_lot_is_inclusive():
    # v = u % total; the first entry whose running sum reaches v wins (v == 30 still picks the first).
    assert melding.lot([30, 70], 30) == 0
    assert melding.lot([30, 70], 31) == 1
    assert melding.lot([0, 50, 50], 0) == 1      # zero weights are skipped
    assert melding.lot([0, 0], 5) is None


def test_generators():
    assert melding.generator_index(10, None) == 23
    row = melding.Row(1, 2, 100, (1, 1), (), (), ())
    assert melding.generator_index(11, row) == melding.CYCLUS_GENERATOR + 2
    with pytest.raises(ValueError):
        melding.generator_index(11, None)


@pytest.fixture(scope="module")
def tables():
    return melding.Tables(gamedata.load(Path(GAME), log=lambda m: None)["melding"])


@pytest.mark.skipif(not GAME, reason="needs MHR_GAME_DIR")
def test_matches_the_game(tables):
    runs = json.loads(SAMPLES.read_text(encoding="utf-8"))["runs"]
    seen = set()
    for run in runs:
        m = melding.Melder(tables, run["method"], run["target"], tuple(run["previous"]))
        rng = XorShift128(tuple(int(x, 16) for x in run["state"].split()))
        for n, (skills, slots) in enumerate(run["talismans"], 1):
            t = m.talisman(rng, n)
            got = ([list(s) for s in t.skills], t.slots)
            if t.unsure:   # Cyclus replaced the second skill with an unsaved generator
                assert got[0][0] == skills[0] and got[1] == slots
                continue
            assert got == (skills, slots), (melding.METHODS[run["method"]], run["target"], n)
        seen.add(run["method"])
    assert seen == set(melding.METHODS)


@pytest.mark.skipif(not GAME, reason="needs MHR_GAME_DIR")
def test_targets(tables):
    assert tables.targets(4) == []                          # Rebirth: random
    assert all(r.pick_rate > 0 for r in tables.targets(9))   # Aurora: pick a skill
    with pytest.raises(ValueError):
        melding.Melder(tables, 9)                           # a picked skill is required


@pytest.mark.skipif(not GAME, reason="needs MHR_GAME_DIR")
def test_perfection(tables):
    rng = XorShift128((0xcf7d5e57, 0x1c1f0ad9, 0xb8fd8293, 0xa716b9f8))
    m = melding.Melder(tables, 10)
    rows = [m.talisman(rng, n) for n in range(1, 2001)]
    for t in rows:
        assert 0 < t.perfection <= 1
        lv = [lv for _, lv in t.skills] + [0]
        assert lv[0] <= t.best[0] and lv[1] <= t.best[1] and sum(t.slots) <= t.best[2]
    assert any(t.perfection == 1 for t in rows)
    # Qurious slots come from the mystery table: the best is 3-3-1 (7 slot levels)
    assert {t.best[2] for t in rows} == {7}


# ---- Rust engine (native/core/src/melding.rs) against the Python reference ---------------------------

needs_native = pytest.mark.skipif(not (GAME and melding._native), reason="needs MHR_GAME_DIR and the compiled engine")


@pytest.fixture(scope="module")
def melding_data():
    return gamedata.load(Path(GAME), log=lambda m: None)["melding"]


def _cases(tables):
    for m in melding.METHODS:
        targets = [r.skill for r in tables.targets(m)]
        picks = [targets[0], targets[len(targets) // 2], targets[-1]] if targets else [None]
        for t in picks:
            yield m, t


@needs_native
def test_native_rolls_match_python(tables, melding_data):
    nt = melding.native_tables(melding_data)
    some_skill = tables.rows[10][5].skill
    for k, (m, target) in enumerate(_cases(tables)):
        for previous in ((None, None), (some_skill, 999)):   # carried-over table, incl. a foreign skill
            state = (0x12345678 + k, 0x9ABCDEF0 ^ k, 0x0F1E2D3C + 7 * k, 0xC0FFEE11)
            py = melding.Melder(tables, m, target, previous)
            rng = XorShift128(state)
            want = []
            for n in range(1, 5001):
                t = py.talisman(rng, n)
                want.append(([tuple(s) for s in t.skills], list(t.slots), t.missed, t.unsure, tuple(t.best)))
            got = [([tuple(s) for s in sk], list(sl), mi, un, tuple(be))
                   for sk, sl, mi, un, be in melding._native.meld_rolls(nt, m, target, list(state), 5000, previous)]
            assert got == want, (melding.METHODS[m], target, previous)


@needs_native
def test_native_matches_the_game(melding_data):
    nt = melding.native_tables(melding_data)
    for run in json.loads(SAMPLES.read_text(encoding="utf-8"))["runs"]:
        state = [int(x, 16) for x in run["state"].split()]
        rows = melding._native.meld_rolls(nt, run["method"], run["target"], state, len(run["talismans"]),
                                          tuple(run["previous"]))
        for (skills, slots), (sk, sl, _, unsure, _) in zip(run["talismans"], rows):
            if unsure:
                assert [list(sk[0]), list(sl)] == [skills[0], slots]
            else:
                assert ([list(x) for x in sk], list(sl)) == (skills, slots)


@needs_native
def test_native_scan_matches_python(tables, melding_data, monkeypatch):
    gens = [XorShift128((0x1000 + i, 0x2000 + i, 0x3000 + 3 * i, 0x4000 ^ i)) for i in range(56)]
    scorer = melding.Scorer({int(r.skill): 10.0 + r.skill % 5 for r in tables.rows[10]}, [0, 7, 15, 24, 36], {})
    wex = tables.rows[10][7].skill
    cases = [((), (0, 0, 0)), (((wex, 1),), (0, 0, 0)), ((), (2, 1, 0)), (((wex, 1), (tables.rows[10][3].skill, 1)), (0, 0, 0))]
    for m, target in [(10, None), (4, None), (2, tables.targets(2)[0].skill), (11, tables.targets(11)[-1].skill)]:
        for wanted, slots in cases:
            for sort, d in (("n", 1), ("rank", 1), ("score", -1), ("perfection", -1), ("n", -1)):
                args = (melding_data, gens, m, target, 8000, list(wanted), list(slots), scorer, sort, d, 50)
                fast = melding.scan(*args)
                monkeypatch.setenv("QURIOUS_ENGINE", "python")
                ref = melding.scan(*args)
                monkeypatch.delenv("QURIOUS_ENGINE")
                assert (fast.scanned, fast.matches, fast.first_match) == (ref.scanned, ref.matches, ref.first_match)
                key = lambda f: (f.n, f.talisman.skills, f.talisman.slots, f.score, round(f.perfection, 9), f.rank)
                assert [key(f) for f in fast.rows] == [key(f) for f in ref.rows], (m, wanted, slots, sort, d)


@pytest.mark.skipif(not GAME, reason="needs MHR_GAME_DIR")
def test_best_for_owned_talismans(tables):
    # Whatever a method made, best_for finds a method whose best talisman with those skills is at least as good.
    for m, target in [(10, None), (4, None), (2, tables.targets(2)[0].skill), (11, tables.targets(11)[0].skill)]:
        melder = melding.Melder(tables, m, target)
        rng = XorShift128((0xDEADBEEF, 0x12345678 + m, 0x0BADF00D, 0x55AA55AA))
        for n in range(1, 1001):
            t = melder.talisman(rng, n)
            if not t.skills:
                continue
            best, method = tables.best_for(t.skills)
            assert method is not None
            assert sum(lv for _, lv in t.skills) + sum(t.slots) <= sum(best)
