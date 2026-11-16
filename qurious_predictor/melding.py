"""Talisman melding (Melding Pot) simulation for every method.

Reconstructed with REFramework probes (tools/probes/talisman_trace.lua) and checked against the game:
every talisman of 9 methods matched, and Qurious Melding: Cyclus matched except where the game falls back
to a generator that is not in the save (see ``Talisman.unsure``).

One talisman, in the game's order (snow.data.alchemy.ReserveFunc / LotFunc), drawing from the method's own
FacilityDataManager._RandomManual generator:

1. updateRandomSkillTableDataList -- a random "table" of two skills:
   slot 0: grade lot, then a skill of that grade. Random methods: skill 1. Methods where the player picks
           skill 1: the skill used when that pick misses.
   slot 1: grade lot, then a skill of that grade for the second skill (never the same as slot 0, nor the
           picked skill).
   Picks are uniform (u % count) over the rows that have rates for that use; the two "Qurious" methods
   weight them by GradePickRate. A grade lot is drawn even when its list is all zero.
2. lotFirstSkill -- one draw (the pick succeeds if u % 100 < PickRate; unused by random methods), one draw
   for the level (Skill1RateList, or MissRateList when the pick missed).
3. lotSecondSkill -- present if u % 100 < SecondSkillLotRate[grade of skill 1][method]; one more draw for
   its level (Skill2RateList).
4. Slots -- Qurious methods: one draw over MysterySlotNumTable. Others: one draw per slot from SlotNumTable
   (block = slot index, row = the two skill grades, table = the method), stopping at an empty slot, after a
   level-4 slot, or at three slots.

Every weighted lot is ``v = u % total`` and picks the first entry whose running sum reaches v (inclusive).
"""

from __future__ import annotations

import heapq
import os
from dataclasses import dataclass, field

from .rng import XorShift128

# Method (AlchemyPatturnData.PatturnTypes) -> English in-game name.
METHODS = {
    0: "Melding—Reflecting Pool", 1: "Melding—Haze", 2: "Melding—Moonbow", 3: "Melding—Wisp of Mystery",
    4: "Melding—Rebirth", 7: "Melding—Anima", 8: "Melding—Reincarnation", 9: "Melding—Aurora",
    10: "Qurious Melding—Vigor", 11: "Qurious Melding—Cyclus",
}
ORDER = [0, 1, 2, 3, 4, 7, 8, 9, 10, 11]          # AlchemyPatturnData.convertAlchemyTypeToIndex
TARGETED = {0, 1, 2, 9, 11}                        # the player picks skill 1
QURIOUS = {10, 11}                                 # weighted picks, mystery slot table
GENERATOR = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 7: 11, 8: 12, 9: 13, 10: 23}   # _RandomManual index
CYCLUS_GENERATOR = 25                              # + grade of the picked skill (C..S)
SLOT_TABLE = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 7: 5, 8: 7, 9: 6}
NO_GRADE = 4                                       # SlotNumTable row for "no second skill"


def lot(weights, u: int):
    total = sum(weights)
    if total == 0:
        return None
    v = u % total
    acc = 0
    for i, w in enumerate(weights):
        acc += w
        if w and v <= acc:
            return i
    return None


@dataclass(frozen=True)
class Row:
    skill: int
    grade: int
    pick_rate: int
    grade_pick: tuple
    skill1: tuple
    miss: tuple
    skill2: tuple


@dataclass
class Talisman:
    n: int
    skills: list = field(default_factory=list)     # [(skill id, level)]
    slots: list = field(default_factory=list)      # 3 slot levels, highest first
    missed: bool = False                           # the picked skill missed (skill 1 is a random one)
    unsure: bool = False                           # second skill decided outside the save (Cyclus)
    # The most this talisman could have had with the same skills: (skill 1 level, skill 2 level, total of
    # the slot levels). A missing second skill counts as the best second skill level the method gives.
    best: tuple = (0, 0, 0)

    @property
    def perfection(self) -> float:
        """Skill levels plus slot levels, as a share of ``best`` (1.0 = the best possible talisman)."""
        have = sum(lv for _, lv in self.skills) + sum(self.slots)
        top = sum(self.best)
        return have / top if top else 0.0


def top_level(rates) -> int:
    """Highest level a rate list can give (0 if none)."""
    return max((i + 1 for i, w in enumerate(rates) if w), default=0)


class Tables:
    def __init__(self, melding: dict):
        self.rows = {p: [] for p in METHODS}
        for p, sid, grade, pick, gp, s1, miss, s2 in melding["skills"]:
            if p in self.rows and sid:
                self.rows[p].append(Row(sid, grade, pick, tuple(gp), tuple(s1), tuple(miss), tuple(s2)))
        self.grades = {int(k): v for k, v in melding["grades"].items()}
        self.second = {int(k): v for k, v in melding["second"].items()}
        self.slots = melding["slots"]
        self.mystery = melding["mystery_slots"]

    def best_slots(self, method: int, g1: int, g2: int) -> int:
        """Largest total of slot levels the method can give a talisman with these skill grades."""
        if method in QURIOUS:
            return max(sum(lv) for w, lv in self.mystery if w)

        def best(k: int) -> int:
            if k == 3:
                return 0
            params = next(q for q in self.slots[k] if (q[0], q[1]) == (g1, g2))
            options = [lv for lv, w in enumerate(params[2][SLOT_TABLE[method]]) if w and lv]
            return max((lv + (0 if lv == 4 else best(k + 1)) for lv in options), default=0)
        return best(0)

    def best_second_level(self, method: int) -> int:
        rows = self.rows[method]
        if method in QURIOUS:
            return max((top_level(r.skill2) for r in rows if r.grade_pick[1]), default=0)
        return max((top_level(r.skill2) for r in rows), default=0)

    def targets(self, method: int) -> list[Row]:
        """Skills the player can pick for skill 1 (empty for random methods)."""
        if method not in TARGETED:
            return []
        return [r for r in self.rows[method] if r.pick_rate > 0]


    def possible(self, method: int) -> set[int]:
        """Skills the method can ever put on a talisman."""
        rows = self.rows[method]
        if method in QURIOUS:
            return {r.skill for r in rows if any(r.grade_pick) or r.pick_rate}
        return {r.skill for r in rows if r.pick_rate or any(r.skill1) or any(r.miss) or any(r.skill2)}


def generator_index(method: int, target: Row | None) -> int:
    if method == 11:
        if target is None:
            raise ValueError("Qurious Melding—Cyclus needs the picked skill")
        return CYCLUS_GENERATOR + target.grade
    return GENERATOR[method]


class Melder:
    def __init__(self, tables: Tables, method: int, target_skill: int | None = None, previous=(None, None)):
        if method not in METHODS:
            raise ValueError(f"unknown melding method {method}")
        self.t = tables
        self.method = method
        self.rows = tables.rows[method]
        self.target = None
        if method in TARGETED:
            matches = [r for r in tables.targets(method) if r.skill == target_skill]
            if not matches:
                raise ValueError("pick a skill for this melding method")
            self.target = matches[0]
        # ReserveInfo.RandomSkillTableList. It lives only in memory and persists between talismans made
        # in the same queue slot (``previous``: its skill ids); after loading the save it is empty.
        by_id = {r.skill: r for r in self.rows}
        self.table = [None if sid is None else by_id.get(sid, Row(sid, -1, 0, (0, 0), (), (), ()))
                      for sid in previous]

    def _pick(self, u: int, cands: list, col: int):
        if self.method in QURIOUS:
            i = lot([r.grade_pick[col] for r in cands], u)
            return None if i is None else cands[i]
        return cands[u % len(cands)]

    def _update(self, rng: XorShift128) -> bool:
        m = self.method
        p1, p, p2 = self.t.grades[m]
        unsure = False
        # slot 0
        grade = lot(p if m in TARGETED else p1, rng.next_u32())
        if grade is not None:
            if m in QURIOUS:
                cands = [r for r in self.rows if r.grade == grade and r.grade_pick[0]]
            elif m in TARGETED:
                cands = [r for r in self.rows if r.grade == grade and any(r.miss)]
            else:
                cands = [r for r in self.rows if r.grade == grade and any(r.skill1)]
            if cands:
                self.table[0] = self._pick(rng.next_u32(), cands, 0)
        # slot 1
        grade = lot(p2, rng.next_u32())
        if grade is not None:
            excl = {r.skill for r in (self.table[0], None if m in QURIOUS else self.target) if r is not None}
            if m in QURIOUS:
                cands = [r for r in self.rows if r.grade == grade and r.grade_pick[1] and r.skill not in excl]
            else:
                cands = [r for r in self.rows if r.grade == grade and any(r.skill2) and r.skill not in excl]
            if cands:
                pick = self._pick(rng.next_u32(), cands, 1)
                if m in QURIOUS and self.target is not None and pick is not None and pick.skill == self.target.skill:
                    # Cyclus removes a second skill equal to the picked one and replaces it using a
                    # generator that is not saved: which skill it becomes cannot be predicted.
                    unsure = True
                self.table[1] = pick
        return unsure

    def talisman(self, rng: XorShift128, n: int = 0) -> Talisman:
        m = self.method
        out = Talisman(n)
        out.unsure = self._update(rng)
        u_pick, u_level = rng.next_u32(), rng.next_u32()
        if self.target is not None and u_pick % 100 < self.target.pick_rate:
            row, lv = self.target, lot(self.target.skill1, u_level)
        else:
            row = self.table[0]
            out.missed = self.target is not None
            lv = None if row is None else lot(row.miss if self.target is not None else row.skill1, u_level)
        if row is None or lv is None:
            out.slots = [0, 0, 0]
            return out
        out.skills.append((row.skill, lv + 1))
        u = rng.next_u32()
        second = self.table[1]
        if second is not None and u % 100 < self.t.second[row.grade][ORDER.index(m)]:
            lv2 = lot(second.skill2, rng.next_u32())
            if lv2 is not None:
                out.skills.append((second.skill, lv2 + 1))
        else:
            out.unsure = False
        grades = (row.grade, second.grade if len(out.skills) > 1 else NO_GRADE)
        if m in QURIOUS:
            out.slots = list(self.t.mystery[lot([w for w, _ in self.t.mystery], rng.next_u32())][1])
        else:
            slots = []
            for k in range(3):
                params = next(q for q in self.t.slots[k] if (q[0], q[1]) == grades)
                level = lot(params[2][SLOT_TABLE[m]], rng.next_u32())
                if not level:
                    break
                slots.append(level)
                if level == 4:
                    break
            out.slots = sorted(slots, reverse=True)
        out.slots = (sorted(out.slots, reverse=True) + [0, 0, 0])[:3]
        max1 = top_level(row.miss if out.missed else row.skill1)
        if len(out.skills) > 1:
            out.best = (max1, top_level(second.skill2), self.t.best_slots(m, *grades))
        elif self.t.second[row.grade][ORDER.index(m)] > 0:
            # no second skill this time, though there could have been one
            p2 = self.t.grades[m][2]
            g2s = [g for g, w in enumerate(p2) if w] or [NO_GRADE]
            out.best = (max1, self.t.best_second_level(m), max(self.t.best_slots(m, row.grade, g) for g in g2s))
        else:
            out.best = (max1, 0, self.t.best_slots(m, row.grade, NO_GRADE))
        return out


def predict(tables: Tables, generators: list, method: int, target_skill: int | None, count: int) -> list[Talisman]:
    """The next ``count`` talismans ``method`` will make, from the generator states in the save."""
    melder = Melder(tables, method, target_skill)
    rng = generators[generator_index(method, melder.target)].copy()
    return [melder.talisman(rng, n) for n in range(1, count + 1)]


# ---- scan: many talismans, filtered, scored, only the rows the app shows ------------------------------
# The Rust engine (native/core/src/melding.rs) does the same, millions of times faster; this is the
# reference it is tested against, used when the extension is missing or QURIOUS_ENGINE=python.

try:
    from . import _native
except ImportError:  # pragma: no cover - built by `pip install -e .`
    _native = None

SORTS = ("n", "rank", "score", "perfection")


@dataclass
class Scorer:
    weights: dict          # skill id -> weight per level
    slot_values: list      # value of a slot by level 0-4
    max_levels: dict       # skill id -> max level (1-based)

    def score(self, t: Talisman) -> int:
        """Score x 100, rounded."""
        total = sum(self.weights.get(sid, 0.0) * min(lv, self.max_levels.get(sid, 99)) for sid, lv in t.skills)
        total += sum(self.slot_values[min(max(lv, 0), 4)] for lv in t.slots)
        return round(total * 100)


def matches(t: Talisman, wanted: list, min_slots: list) -> bool:
    """``wanted`` = [(skill, min level)]: two different skills of the talisman, in either position."""
    used = set()
    for sid, lv in wanted:
        k = next((i for i, (s, l) in enumerate(t.skills) if i not in used and s == sid and l >= max(lv, 1)), None)
        if k is None:
            return False
        used.add(k)
    return all(h >= n for n, h in zip(sorted(min_slots, reverse=True), t.slots))


@dataclass
class Found:
    n: int
    talisman: Talisman
    score: float
    perfection: float
    rank: int          # 1 + scanned talismans with a higher score (equal scores share a rank)


@dataclass
class ScanResult:
    scanned: int
    matches: int
    first_match: int | None
    rows: list


def use_native() -> bool:
    return _native is not None and os.environ.get("QURIOUS_ENGINE", "").lower() != "python"


_NATIVE_TABLES = {}


def native_tables(melding: dict):
    key = id(melding)
    if key not in _NATIVE_TABLES:
        _NATIVE_TABLES.clear()
        _NATIVE_TABLES[key] = (melding, _native.MeldTables(
            [tuple(x) for x in melding["skills"]],
            {int(k): tuple(v) for k, v in melding["grades"].items()},
            {int(k): v for k, v in melding["second"].items()},
            [[(a, b, t) for a, b, t in block] for block in melding["slots"]],
            [(w, lv) for w, lv in melding["mystery_slots"]]))
    return _NATIVE_TABLES[key][1]


def scan(melding: dict, generators: list, method: int, target_skill: int | None, count: int, wanted: list,
         min_slots: list, scorer: Scorer, sort: str = "n", direction: int = 1, limit: int = 1000) -> ScanResult:
    """Simulate ``count`` talismans; keep the ``limit`` best matches for ``sort`` (ties by number)."""
    if sort not in SORTS:
        raise ValueError(f"unknown sort {sort}")
    tables = Tables(melding)
    melder = Melder(tables, method, target_skill)       # validates the method and the picked skill
    state = generators[generator_index(method, melder.target)].state()
    wanted = [(int(s), int(lv)) for s, lv in wanted]
    min_slots = [int(x) for x in min_slots]
    if use_native():
        sv = [float(x) for x in scorer.slot_values]
        scanned, n_match, first, rows = _native.meld_scan(
            native_tables(melding), method, target_skill, list(state), int(count), wanted, min_slots,
            [(int(k), float(v)) for k, v in scorer.weights.items()], sv,
            {int(k): int(v) for k, v in scorer.max_levels.items()}, sort, int(direction), int(limit))
        found = []
        for n, (skills, slots, missed, unsure, best), score, perf, rank in rows:
            t = Talisman(n, [tuple(x) for x in skills], list(slots), missed, unsure, tuple(best))
            found.append(Found(n, t, score, perf, rank))
        return ScanResult(scanned, n_match, first, found)
    rng = XorShift128(state)
    hist = {}
    heap = []          # (-key, -n, Found): the heap top is the worst kept row
    n_match, first = 0, None
    for n in range(1, count + 1):
        t = melder.talisman(rng, n)
        sc = scorer.score(t)
        hist[sc] = hist.get(sc, 0) + 1
        if not matches(t, wanted, min_slots):
            continue
        n_match += 1
        first = first or n
        if not limit:
            continue
        key = direction * {"n": n, "rank": -sc, "score": sc, "perfection": t.perfection}[sort]
        item = (-key, -n, Found(n, t, sc / 100, t.perfection, 0))
        if len(heap) < limit:
            heapq.heappush(heap, item)
        elif item[:2] > heap[0][:2]:
            heapq.heapreplace(heap, item)
    above, acc = {}, 0
    for sc in sorted(hist, reverse=True):
        above[sc] = acc
        acc += hist[sc]
    rows = [f for _, _, f in sorted(heap, key=lambda x: (-x[0], -x[1]))]
    for f in rows:
        f.rank = 1 + above[round(f.score * 100)]
    return ScanResult(count, n_match, first, rows)
