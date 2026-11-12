"""Re-implementation of snow.data.ArmorCustomBuildupData.createResult (qurious armor crafting).

Reconstructed from black-box traces (see docs/RESEARCH.md). Every random draw is a genU32() call
on the generator selected by the augment's cost tier and type; ``u % total`` picks from weights.
"""

from __future__ import annotations

from dataclasses import dataclass

from .rng import XorShift128

# snow.data.DataDef.CustomBuildupCategoryId
CAT_DEF = 13
CAT_RES = 14
CAT_RES_PENALTY = 15
CAT_SLOT = 19
CAT_SKILL = 20

LOT_CATEGORIES = [CAT_DEF, CAT_RES, CAT_SLOT, CAT_SKILL]
MAX_ENTRIES = 7
MAX_SKILLS_PER_PIECE = 5
MAX_LOTS = 52  # the game gives up after 52 lots even if cost is left (fits 3x458 recorded rolls)

# Augment types (GuiCustomBuildup.BuildupType).
TYPE_AUGMENT = 0
TYPE_SKILL = 1
TYPE_SLOT = 2
TYPE_STABILITY = 3
# Names as in the game's Qurious Crafting menu, listed in menu order.
TYPE_NAMES = {TYPE_AUGMENT: "Augment", TYPE_STABILITY: "Augment: Stability", TYPE_SKILL: "Augment: Skills+",
              TYPE_SLOT: "Augment: Slots+"}

# Buildup ids used by the forced first lots of each augment type.
ID_SKILL_DOWN = 149
ID_DEF_PENALTY = 61
FORCED_CATEGORY = {
    (TYPE_AUGMENT, 0): CAT_DEF,
    (TYPE_AUGMENT, 1): CAT_SKILL,
    (TYPE_SKILL, 0): CAT_SKILL,
    (TYPE_SKILL, 1): CAT_RES_PENALTY,
    (TYPE_SKILL, 2): CAT_SKILL,
    (TYPE_SLOT, 0): CAT_SKILL,
    (TYPE_SLOT, 1): CAT_DEF,
    (TYPE_SLOT, 2): CAT_SLOT,
    (TYPE_STABILITY, 0): CAT_DEF,
}
FORCED_IDS = {
    (TYPE_SKILL, 0): [ID_SKILL_DOWN],
    (TYPE_SKILL, 2): [146, 147, 148],
    (TYPE_SLOT, 0): [ID_SKILL_DOWN],
    (TYPE_SLOT, 1): [ID_DEF_PENALTY],
    (TYPE_SLOT, 2): [139, 140],
}


def seed_index(cost: int, buildup_type: int) -> int:
    """FacilityDataManager.RandomSeedManual used for an augment: CustomBuildup_TT_YY.

    Tier TT = (cost - 10) / 2 + 1 (cost 10..20), type YY = buildup_type + 1. Confirmed in game
    for cost 10; other tiers follow the enum layout (CustomBuildup_01_01 = 32 ... _06_04 = 55).
    """
    tier = (cost - 10) // 2
    if not 0 <= tier <= 5:
        return 18  # RandomSeedManual.CustomBuildup
    return 32 + tier * 4 + buildup_type


@dataclass(frozen=True)
class Buildup:
    table: int
    id: int
    category: int
    cost: int
    values: tuple[int, ...]
    lots: tuple[int, ...]


@dataclass(frozen=True)
class Entry:
    category: int
    id: int
    value: int
    skill: int  # PlEquipSkillId for skill entries, else 0
    cost: int

    def group(self):
        if self.category == CAT_DEF:
            return ("def",)
        if self.category == CAT_RES:
            return ("res", element_of(self.id))
        if self.category == CAT_SKILL:
            return ("skill", self.skill)
        return None


ELEMENTS = ["fire", "water", "thunder", "ice", "dragon"]


def element_of(buildup_id: int) -> int:
    """Resistance buildups come in blocks of 10 ids starting at 89: fire, water, thunder, ice, dragon."""
    return (buildup_id - 89) // 10


class Tables:
    """The qurious tables needed by the simulation."""

    def __init__(self, base: list[Buildup], armor_lots: list[tuple[int, int, int, int]],
                 category_lots: dict[int, list[int]], skill_costs: list[tuple[int, int]],
                 max_levels: dict[int, int] | None = None):
        self.base = {(b.table, b.id): b for b in base}
        self.lots: dict[int, dict[int, list[tuple[int, int]]]] = {}
        for table, category, bid, lot in armor_lots:
            self.lots.setdefault(table, {}).setdefault(category, []).append((bid, lot))
        self.category_lots = category_lots
        self.skill_costs = skill_costs  # (skill id, cost) in table order
        self.max_levels = max_levels or {}

    def skills_with_cost(self, cost: int) -> list[int]:
        return [s for s, c in self.skill_costs if c == cost]


def _pick(items: list, weights: list[int], rng: XorShift128):
    total = sum(weights)
    if total <= 0:
        return None
    r = rng.next_u32() % total
    acc = 0
    for item, w in zip(items, weights):
        acc += w
        if r < acc:
            return item
    return items[-1]


def _value_index(b: Buildup, rng: XorShift128) -> int:
    if sum(1 for x in b.lots if x > 0) <= 1:
        return 0
    return _pick(list(range(len(b.lots))), list(b.lots), rng)


def create_result(rng: XorShift128, tables: Tables, table: int, total_cost: int,
                  armor_skills: list[tuple[int, int]], buildup_type: int,
                  rules: dict | None = None) -> list[Entry]:
    """One augment roll. ``armor_skills`` = [(skill id, level)] in the armor's order.

    Advances ``rng`` exactly like the game does.
    """
    rules = rules or {}
    lots = tables.lots.get(table, {})
    cat_weights = list(tables.category_lots.get(table, [40, 30, 10, 20]))
    levels = {s: lv for s, lv in armor_skills if s}
    armor_skills = [s for s, _ in armor_skills if s]
    remaining = total_cost
    res: list[Entry] = []

    def drop_zero_group(group) -> None:
        nonlocal remaining, res
        if group and sum(e.value for e in res if e.group() == group) == 0:
            for e in res:
                if e.group() == group:
                    remaining += e.cost
            res = [e for e in res if e.group() != group]

    k = 0
    while k < MAX_LOTS:
        if len(res) == MAX_ENTRIES - 1:
            # Last entry: spend what is left on the largest defense buildup that fits (no lot).
            fits = [tables.base[(table, i)] for i, _ in lots.get(CAT_DEF, [])
                    if 0 < tables.base[(table, i)].cost <= remaining]
            if not fits:
                break
            b = max(fits, key=lambda x: x.cost)
            vi = _value_index(b, rng)
            res.append(Entry(CAT_DEF, b.id, b.values[vi], 0, b.cost))
            remaining -= b.cost
            if sum(e.value for e in res if e.category == CAT_DEF) == 0:
                drop_zero_group(("def",))
                continue
            break

        category = FORCED_CATEGORY.get((buildup_type, k))
        if category is None:
            category = _pick(LOT_CATEGORIES, cat_weights, rng)
            if buildup_type == TYPE_STABILITY and category == CAT_SKILL:
                category = CAT_DEF
        forced = FORCED_IDS.get((buildup_type, k))
        if forced:
            cands = [(i, l if l > 0 else 1) for i, l in lots.get(category, []) if i in forced]
        else:
            cands = [(i, l) for i, l in lots.get(category, []) if l > 0
                     and (buildup_type != TYPE_STABILITY or tables.base[(table, i)].cost > 0)]
        k += 1
        if not cands:
            continue
        if len(cands) == 1:
            bid = cands[0][0]
        else:
            bid = _pick([c[0] for c in cands], [c[1] for c in cands], rng)
        b = tables.base[(table, bid)]
        vi = _value_index(b, rng)
        skill = 0
        if category == CAT_SKILL:
            if b.cost > 0:
                pool = tables.skills_with_cost(b.cost)
                skill = pool[rng.next_u32() % len(pool)] if pool else 0
            elif armor_skills:
                skill = armor_skills[rng.next_u32() % len(armor_skills)]
        ok, why = b.cost <= remaining, "cost"
        if ok and category == CAT_SKILL:
            adding = b.cost > 0
            same = sum(1 for e in res if e.category == CAT_SKILL and e.skill == skill and (e.cost > 0) == adding)
            removed = {e.skill for e in res if e.category == CAT_SKILL and e.cost < 0}
            added = {e.skill for e in res if e.category == CAT_SKILL and e.cost > 0}
            if adding and forced and skill in removed:
                ok, why = False, "conflict"  # the forced Skills+ skill is re-lotted (below)
            if not adding and same >= levels.get(skill, 0):
                ok, why = False, "level"  # cannot remove more levels than the armor has
            if adding and skill not in levels and skill not in added:
                # A new skill needs a free skill slot: a piece holds at most 5 skills, and every
                # entry of a new skill uses one (the same new skill may then be raised again).
                used = len(levels) + sum(1 for e in res if e.category == CAT_SKILL and e.cost > 0
                                         and e.skill not in levels)
                if used >= MAX_SKILLS_PER_PIECE:
                    ok, why = False, "slots"
            if adding and levels.get(skill, 0) + same > tables.max_levels.get(skill, 99):  # 0-based max
                ok, why = False, "max level"
        if not ok and why == "conflict":
            k -= 1  # the game repeats the forced lot
        if ok:
            entry = Entry(category, bid, b.values[vi], skill, b.cost)
            res.append(entry)
            remaining -= b.cost
            drop_zero_group(entry.group())
        if remaining == 0:
            break
    return res


@dataclass
class Summary:
    defense: int
    slots: int
    resistances: dict[str, int]
    skills: list[tuple[int, int]]  # (skill id, +1/-1)


def summarize(entries: list[Entry]) -> Summary:
    res = {}
    for e in entries:
        if e.category in (CAT_RES, CAT_RES_PENALTY):
            el = ELEMENTS[element_of(e.id)]
            res[el] = res.get(el, 0) + e.value
    return Summary(
        defense=sum(e.value for e in entries if e.category == CAT_DEF),
        slots=sum(e.value for e in entries if e.category == CAT_SLOT),
        resistances={k: v for k, v in res.items() if v},
        skills=[(e.skill, e.value) for e in entries if e.category == CAT_SKILL],
    )
