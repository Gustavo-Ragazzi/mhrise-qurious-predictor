"""Validation against data recorded in the game (skipped unless the recordings are available).

* MHR_GAME_DIR      game install (tables are extracted from it)
* MHR_QURIOUS_DATA  folder with QuriousProbe.txt, QuriousTrace.txt and "458 times.csv"
  (reframework/data after running tools/probes/*.lua and the "Qurious Preview and Export as csv"
  mod on Valstrax Helm - Epoch / Valstrax Coil - Epoch / Prudence Coil).
"""

import collections
import os
import re
from pathlib import Path

import pytest

from qurious_predictor import engine, gamedata
from qurious_predictor.rng import XorShift128

GAME = os.environ.get("MHR_GAME_DIR")
DATA = os.environ.get("MHR_QURIOUS_DATA")
pytestmark = pytest.mark.skipif(not (GAME and DATA), reason="needs MHR_GAME_DIR and MHR_QURIOUS_DATA")


@pytest.fixture(scope="module")
def gd():
    return gamedata.load(Path(GAME))


def _state(hexstr):
    return [int(hexstr[i:i + 8], 16) for i in range(0, 32, 8)]


def _generators():
    text = (Path(DATA) / "QuriousProbe.txt").read_text(encoding="utf-8", errors="replace")
    return {int(m[1]): [int(m[i], 16) for i in range(2, 6)]
            for m in re.finditer(r"^  \[(\d+)\] StateId=\S+ raw=(\w+) (\w+) (\w+) (\w+)", text, re.M)}


def _armor(gd, name):
    return next(a for a in gd["armors"].values() if a["names"].get("en") == name)


def test_trace(gd):
    """160 createResult calls from known generator states (Valstrax Helm - Epoch, every type)."""
    tables = gamedata.tables(gd)
    helm = _armor(gd, "Valstrax Helm - Epoch")
    text = (Path(DATA) / "QuriousTrace.txt").read_text(encoding="utf-8", errors="replace")
    n = 0
    for m in re.finditer(r"^createResult type(\d) i=\d+ pre=(\w{32}) ret=(.*) post=(\w{32})$", text, re.M):
        rng = XorShift128(_state(m[2]))
        out = engine.create_result(rng, tables, helm["table"], helm["cost"], [tuple(x) for x in helm["skills"]], int(m[1]))
        got = sorted(f"{e.category}/{e.id}/v{e.value}/s{e.skill}/c{e.cost}" for e in out)
        assert got == sorted(m[3].split()), m[0][:60]
        assert list(rng.state()) == _state(m[4])
        n += 1
    assert n == 160


def _label(gd, e):
    if e.category == engine.CAT_DEF:
        return "Def"
    if e.category in (engine.CAT_RES, engine.CAT_RES_PENALTY):
        return engine.ELEMENTS[engine.element_of(e.id)].capitalize() + " Res"
    if e.category == engine.CAT_SLOT:
        return "Slot+"
    return gd["skills"][str(e.skill)]["en"]


def _csv_runs():
    runs, cur = [], None
    for line in (Path(DATA) / "458 times.csv").read_text(encoding="utf-8").splitlines():
        if line.startswith("No,"):
            cur = collections.defaultdict(list)
            runs.append(cur)
            continue
        no, typ, val = line.split(",")
        label = typ.split("`", 1)[1]
        if ":" in label:
            label = label.split(":", 1)[1]
        cur[int(no)].append((label, int(val)))
    return runs


@pytest.mark.parametrize("run,armor,btype", [
    (0, "Prudence Coil", engine.TYPE_STABILITY),
    (1, "Valstrax Coil - Epoch", engine.TYPE_AUGMENT),  # the mod recorded type 0 (plain Augment) for this run
    (2, "Valstrax Helm - Epoch", engine.TYPE_SLOT),
])
def test_mod_csv(gd, run, armor, btype):
    """458 consecutive rolls per run exported by the Nexus mod (all cost-10 armor)."""
    tables = gamedata.tables(gd)
    a = _armor(gd, armor)
    rng = XorShift128(_generators()[engine.seed_index(a["cost"], btype)])
    rows = _csv_runs()[run]
    for no in range(1, 459):
        out = engine.create_result(rng, tables, a["table"], a["cost"], [tuple(x) for x in a["skills"]], btype)
        got = sorted((_label(gd, e), e.value) for e in out)
        assert got == sorted(rows[no]), f"roll {no}"


def test_real_rolls(gd):
    """Five real Slots+ augments on Valstrax Helm - Epoch, read off the game screen."""
    tables = gamedata.tables(gd)
    helm = _armor(gd, "Valstrax Helm - Epoch")
    rng = XorShift128(_generators()[engine.seed_index(helm["cost"], engine.TYPE_SLOT)])
    name = lambda s: gd["skills"][str(s)]["en"]
    seen = [
        (-25, 1, {"dragon": 2}, {("Tune-Up", 1), ("Dragon Conversion", -1)}),
        (-20, 2, {"water": 1}, {("Attack Boost", -1)}),
        (-21, 1, {"ice": -3}, {("Paralysis Resistance", 1), ("Dragon Conversion", -1)}),
        (-14, 1, {}, {("Item Prolonger", 1), ("Dragon Conversion", -1)}),
        (-12, 1, {"ice": -2, "fire": 2}, {("Attack Boost", -1)}),
    ]
    for d, slots, res, skills in seen:
        s = engine.summarize(engine.create_result(rng, tables, helm["table"], helm["cost"],
                                                  [tuple(x) for x in helm["skills"]], engine.TYPE_SLOT))
        assert (s.defense, s.slots, s.resistances, {(name(k), v) for k, v in s.skills}) == (d, slots, res, skills)
