"""Real augments read off the game screen that pin down rules of createResult.

* Flaming Espinas Grip, Slots+ cost 10: roll 17 removes Intrepid Heart (forced -1, cost -10) and
  later adds Intrepid Heart +1 (cost 6). The group sums to 0 and is dropped with its cost refunded,
  which leaves the cost left below 0: the game ends the roll there (11 draws), so roll 18 is
  Razor Sharp -2, defense -12, dragon +1, +2 slot points, as seen in game.
"""
import os
from pathlib import Path

import pytest

from qurious_predictor import engine, gamedata, search

GAME = os.environ.get("MHR_GAME_DIR")
pytestmark = pytest.mark.skipif(not (GAME and search._native), reason="needs MHR_GAME_DIR and the compiled engine")

# the Slots+ cost 10 generator of a save, before the rolls below
STATE = (3431597797, 1326392685, 2179619026, 828648148)


def test_kaiser_uses_generator_35_not_the_enum_cost_tier():
    gd = gamedata.load(Path(GAME), log=lambda m: None)
    a = next(x for x in gd['armors'].values() if x['names'].get('en') == 'Kaiser Crown X')
    assert engine.seed_index(a['cost'], engine.TYPE_AUGMENT) == 35
    nt = search.native_tables(gd)
    after, row = search._native.augment_advance(nt, [2751145438,2451486738,3155500154,666053897],
        a['table'], a['cost'], [tuple(s) for s in a['skills']], engine.TYPE_AUGMENT, 1)
    assert tuple(after) == (3155500154,666053897,364268471,3611330697)
    assert _summary(gd, row) == (16, 0, [0]*5, [])


def _summary(gd, row):
    d, sl, res, sk = row
    name = lambda s: gd["skills"][str(s)]["en"]
    total = {}
    for s, v in sk:
        total[name(s)] = total.get(name(s), 0) + v
    return d, sl, list(res), sorted((k, v) for k, v in total.items() if v)


def test_a_refund_below_zero_ends_the_roll():
    gd = gamedata.load(Path(GAME), log=lambda m: None)
    a = next(x for x in gd["armors"].values() if x["names"].get("en") == "Flaming Espinas Grip")
    nt = search.native_tables(gd)
    rows = search._native.rolls(nt, STATE, a["table"], a["cost"], [tuple(s) for s in a["skills"]], engine.TYPE_SLOT, 18)
    seen = {
        1: (-16, 1, [0, 0, 0, 0, 2], [("Intrepid Heart", -1)]),
        16: (-18, 1, [-3, 0, 0, 0, 0], [("Ballistics", 1), ("Razor Sharp", -1)]),
        17: (-23, 1, [0, 0, 0, 0, 0], [("Water Attack", 1)]),
        18: (-12, 2, [0, 0, 0, 0, 1], [("Razor Sharp", -2)]),
    }
    for n, want in seen.items():
        assert _summary(gd, rows[n - 1]) == want, f"roll {n}"
