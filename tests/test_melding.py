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
