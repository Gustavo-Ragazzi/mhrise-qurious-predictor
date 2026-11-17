"""Set builder and build optimizer: armor sets that reach skill levels, from game armor, the hunter's
own armor and talismans, and future qurious augments and talismans (as many rolls as allowed).

The search itself is ``native/core/src/sets.rs``; this module turns game data, the box and the
generator states into candidates and the results into rows for the app.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from mhrise_exporter.export import _expand_slots, apply_slot_bonus

from . import engine, melding, search

PART_NAMES = ["Head", "Chest", "Arms", "Waist", "Legs"]
RANKS = {"low": (1, 3), "high": (4, 7), "master": (8, 99)}
TALISMAN_SEQ = 100           # talisman sequence ids: TALISMAN_SEQ + melding generator index
TALISMAN_METHODS = (10, 11)  # talisman rolls: Qurious Melding—Vigor and —Cyclus
NO_LIMIT = 2**32 - 1


def native():
    """The compiled engine; the set search has no Python version."""
    if search._native is None:
        raise RuntimeError("The set builder needs the compiled engine (pip install -e . with a Rust toolchain).")
    return search._native


def rank_of(rarity: int) -> str:
    """Rank of an armor piece by its (1-based) rarity."""
    return next(r for r, (lo, hi) in RANKS.items() if lo <= rarity <= hi)


@dataclass
class Options:
    reqs: list                                   # [(skill, min level)]
    weapon: list = field(default_factory=lambda: [0, 0, 0])
    ranks: tuple = ("master",)
    game_armor: bool = True                      # armor from the game (craftable), not only the box
    owned_armor: bool = True                     # the armor in the box (with its qurious augments)
    owned_talismans: bool = True
    qurious_rolls: int = 0                       # future augments per piece and option (0: none)
    qurious_owned_only: bool = False             # roll only pieces in the box
    talisman_rolls: int = 0                      # future talismans per method (0: none)
    owned_decos: bool = False                    # only the decorations the hunter has
    value: str = "defense"                       # "defense" or "score"
    cost_first: bool = True
    weights: dict = field(default_factory=dict)  # skill -> weight per level (score)
    slot_values: list = field(default_factory=lambda: [0.0] * 5)
    max_cost: int = NO_LIMIT
    limit: int = 10
    seconds: float = 20.0                        # search time limit
    floor: float = 0.0                           # only sets worth at least this much


class Builder:
    def __init__(self, data: dict, meld: melding.Tables):
        self.data = data
        self.meld = meld
        self.max_levels = {int(k): v + 1 for k, v in data["max_levels"].items()}
        self.decos = {d["id"]: d for d in data["decorations"]}

    # ---- candidates ------------------------------------------------------------------------------------
    def _armor_candidates(self, o: Options, box_armors, generators, owned_ids):
        """(candidate infos, per-part candidate tuples)."""
        infos, parts = [], [[] for _ in range(5)]

        def add(part, info, skills, slots, defense, seq=-1, roll=0):
            info["key"] = len(infos)
            info["skills"] = [(int(s), int(l)) for s, l in skills if l > 0]
            info["slots"] = [int(x) for x in (list(slots) + [0, 0, 0])[:3]]
            info["defense"] = int(defense)
            infos.append(info)
            parts[part].append((info["key"], info["skills"], tuple(info["slots"]), int(defense), seq, roll))

        ranks = [RANKS[r] for r in o.ranks]
        in_rank = lambda a: any(lo <= a["rare"] + 1 <= hi for lo, hi in ranks)
        if o.game_armor:
            for aid, a in self.data["all_armors"].items():
                if not a["names"] or not in_rank(a):
                    continue
                slots = sorted(_expand_slots(a["slots"]), reverse=True)
                add(a["part"], {"kind": "game", "id": aid, "owned": int(aid) in owned_ids}, a["skills"], slots,
                    a.get("defMax", 0))
        if o.owned_armor:
            seen = set()
            for it in box_armors:
                a = self.data["all_armors"].get(str(it.armor_id))
                if a is None or (not it.augmented and o.game_armor and in_rank(a)):
                    continue      # an unaugmented piece is the game piece
                levels = {sid: lv for sid, lv in a["skills"]}
                for sid, v in it.skills or []:
                    levels[sid] = levels.get(sid, 0) + v
                base = _expand_slots(a["slots"])
                slots = apply_slot_bonus(base, it.slot_points) if it.slot_points else sorted(base, reverse=True)
                key = (it.armor_id, tuple(sorted(levels.items())), tuple(slots), it.defense)
                if key in seen:
                    continue
                seen.add(key)
                add(a["part"], {"kind": "owned", "id": str(it.armor_id), "box": it.index, "augmented": it.augmented,
                                "owned": True, "def": it.defense, "res": list(it.resistances or [0] * 5),
                                "slotPoints": it.slot_points, "augments": list(it.skills or [])},
                    levels.items(), slots, a.get("defMax", 0) + it.defense)
        if o.qurious_rolls > 0 and generators:
            pieces = []
            for aid, a in self.data["armors"].items():
                full = self.data["all_armors"].get(aid)
                if full is None or not in_rank(full) or (o.qurious_owned_only and int(aid) not in owned_ids):
                    continue
                pieces.append((int(aid), a["table"], a["cost"], [tuple(s) for s in a["skills"]], list(a["slots"])))
            # with the fewest rolls first, the score only breaks ties: candidates follow the wanted skills
            weights = o.weights if o.value == "score" and not o.cost_first else {}
            rows = native().augment_candidates(
                search.native_tables(self.data), pieces, [g.state() for g in generators], list(engine.TYPE_NAMES),
                int(o.qurious_rolls), [s for s, _ in o.reqs], {int(k): float(v) for k, v in weights.items()},
                [float(x) for x in o.slot_values])
            for aid, ty, n, skills, slots, ddef, res, delta, points in rows:
                a, full = self.data["armors"][str(aid)], self.data["all_armors"][str(aid)]
                seq = engine.seed_index(a["cost"], ty)
                add(full["part"], {"kind": "roll", "id": str(aid), "type": ty, "n": n, "seq": seq, "cost": a["cost"],
                                   "owned": aid in owned_ids, "def": ddef, "res": list(res),
                                   "augments": [tuple(x) for x in delta], "slotPoints": points},
                    skills, slots, full.get("defMax", 0) + ddef, seq, n)
        return infos, parts

    def _talisman_candidates(self, o: Options, box_talismans, generators):
        infos, cands = [], []

        def add(info, skills, slots, seq=-1, roll=0):
            info["key"] = len(infos)
            infos.append(info)
            cands.append((info["key"], [(int(s), int(l)) for s, l in skills], tuple(int(x) for x in slots), 0, seq, roll))

        if o.owned_talismans:
            seen = set()
            for it in box_talismans:
                key = (tuple(sorted(it.skills)), tuple(it.slots))
                if key not in seen:
                    seen.add(key)
                    add({"kind": "owned", "box": it.index, "skills": list(it.skills), "slots": list(it.slots)},
                        it.skills, it.slots)
        if o.talisman_rolls > 0 and generators:
            weights = {int(k): float(v) for k, v in (o.weights if o.value == "score" and not o.cost_first else {}).items() if v}
            nt = melding.native_tables(self.data["melding"])
            # Qurious Melding only: Vigor (random) and Cyclus with every skill it can pick
            jobs = [(m, row) for m in TALISMAN_METHODS
                    for row in (self.meld.targets(m) if m in melding.TARGETED else [None])]

            def run(job):
                m, row = job
                gen = melding.generator_index(m, row)
                return m, row, gen, native().meld_candidates(
                    nt, m, row.skill if row else None, list(generators[gen].state()), int(o.talisman_rolls),
                    [s for s, _ in o.reqs], weights, [float(x) for x in o.slot_values])

            with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
                results = list(pool.map(run, jobs))
            for m, row, gen, rows in results:
                for n, skills, slots, unsure in rows:
                    add({"kind": "roll", "method": m, "target": row.skill if row else None, "n": n,
                         "unsure": unsure, "skills": [list(s) for s in skills], "slots": list(slots)},
                        skills, slots, TALISMAN_SEQ + gen, n)
        return infos, cands

    def _deco_tuples(self, o: Options, owned_decos):
        out = []
        for d in self.data["decorations"]:
            count = owned_decos.get(d["id"], 0) if o.owned_decos else NO_LIMIT
            if count:
                out.append((d["id"], d["skill"], d["level"], d["points"], count))
        return out

    # ---- search ----------------------------------------------------------------------------------------
    def _common(self, o: Options, owned_decos):
        return ([int(x) for x in o.weapon], self._deco_tuples(o, owned_decos or {}),
                [(int(s), int(l)) for s, l in o.reqs], self.max_levels,
                {int(k): float(v) for k, v in o.weights.items()}, [float(x) for x in o.slot_values], o.value)

    def search(self, o: Options, box_armors=(), box_talismans=(), generators=None, owned_decos=None):
        """The best sets for ``o`` (fewest rolls first with ``cost_first``) and what was searched."""
        owned_ids = {it.armor_id for it in box_armors}
        ainfo, parts = self._armor_candidates(o, box_armors, generators, owned_ids)
        tinfo, tals = self._talisman_candidates(o, box_talismans, generators)
        rows, complete = native().set_search(
            parts, tals, *self._common(o, owned_decos), bool(o.cost_first), int(min(o.max_cost, NO_LIMIT)),
            int(o.limit), float(o.seconds), float(o.floor))
        counts = {"armor": [len(p) for p in parts], "talismans": len(tals), "complete": complete}
        return [Found(ainfo, tinfo, r) for r in rows], counts

    def improve(self, o: Options, starts, box_armors=(), box_talismans=(), generators=None, owned_decos=None):
        """Pareto front (fewest rolls first, each next set worth more) of sets reached from ``starts`` by
        changing one or two parts at a time. ``starts`` = [(5 armor items or None, talisman item or None)]."""
        owned_ids = {it.armor_id for it in box_armors}
        ainfo, parts = self._armor_candidates(o, box_armors, generators, owned_ids)
        tinfo, tals = self._talisman_candidates(o, box_talismans, generators)
        start_tuples = []
        for armor, talisman in starts:
            row = [self._talisman_start(tinfo, talisman)]
            row += [self._armor_start(ainfo, it) for it in armor]
            start_tuples.append(row)
        rows, complete = native().set_improve(
            parts, tals, *self._common(o, owned_decos), int(min(o.max_cost, NO_LIMIT)), int(o.limit),
            start_tuples, float(o.seconds))
        counts = {"armor": [len(p) for p in parts], "talismans": len(tals), "complete": complete}
        return [Found(ainfo, tinfo, r) for r in rows], counts

    def best_and_improve(self, o: Options, current, box_armors=(), box_talismans=(), generators=None,
                         owned_decos=None):
        """Build optimizer: the best set without rolls (exact search, within a few seconds) and the front
        of improvements with rolls, from that set and from ``current`` (5 armor items, talisman item)."""
        base = Options(**{**o.__dict__, "qurious_rolls": 0, "talisman_rolls": 0, "cost_first": False, "limit": 1,
                          "seconds": min(o.seconds, 8.0), "max_cost": 0})
        best, counts0 = self.search(base, box_armors, box_talismans, generators, owned_decos)
        starts = [current] if current else []
        for f in best:
            starts.append(([self._item(p) for p in f.pieces], self._tal_item(box_talismans, f.talisman)))
        if not starts:
            return [], {**counts0, "proven": counts0["complete"]}
        front, counts = self.improve(o, starts, box_armors, box_talismans, generators, owned_decos)
        counts["proven"] = counts0["complete"]
        return front, counts

    @staticmethod
    def _item(info):
        """An armor item for a candidate (augmented or not, as the box has it)."""
        if info is None:
            return None
        from .savedata import ArmorItem
        if info["kind"] == "owned":
            return ArmorItem(int(info["id"]), info.get("augmented", False), defense=info.get("def", 0),
                             resistances=list(info.get("res") or [0] * 5), slot_points=info.get("slotPoints", 0),
                             skills=list(info.get("augments") or []), index=info.get("box", -1))
        return ArmorItem(int(info["id"]), False, resistances=[0] * 5, skills=[])

    @staticmethod
    def _tal_item(box_talismans, info):
        if info is None or info.get("box") is None:
            return None
        return next((it for it in box_talismans if it.index == info["box"]), None)

    def _item_info(self, it) -> dict | None:
        """Candidate info of an armor item (skills and slots with its augments)."""
        a = self.data["all_armors"].get(str(it.armor_id))
        if a is None:
            return None
        levels = {sid: lv for sid, lv in a["skills"]}
        for sid, v in it.skills or []:
            levels[sid] = levels.get(sid, 0) + v
        base = _expand_slots(a["slots"])
        slots = apply_slot_bonus(base, it.slot_points) if it.slot_points else sorted(base, reverse=True)
        owned = it.index >= 0
        info = {"kind": "owned" if owned else "game", "id": str(it.armor_id), "box": it.index if owned else None,
                "augmented": it.augmented, "owned": owned, "def": it.defense, "res": list(it.resistances or [0] * 5),
                "slotPoints": it.slot_points, "augments": list(it.skills or [])}
        info["skills"] = [(int(s), int(l)) for s, l in levels.items() if l > 0]
        info["slots"] = [int(x) for x in (list(slots) + [0, 0, 0])[:3]]
        info["defense"] = int(a.get("defMax", 0) + it.defense)
        return info

    def _armor_start(self, ainfo, it):
        info = self._item_info(it) if it is not None else None
        if info is None:
            return None
        info["key"] = len(ainfo)
        ainfo.append(info)
        return (info["key"], info["skills"], tuple(info["slots"]), info["defense"], -1, 0)

    @staticmethod
    def _talisman_start(tinfo, it):
        if it is None:
            return None
        info = {"kind": "owned", "box": it.index, "skills": list(it.skills), "slots": list(it.slots), "key": len(tinfo)}
        tinfo.append(info)
        return (info["key"], [(int(s), int(l)) for s, l in it.skills], tuple(int(x) for x in it.slots), 0, -1, 0)


class Found:
    """One set from the search: (parts, talisman, decos, skills, free slots, cost, defense, score)."""

    @classmethod
    def of(cls, pieces, talisman, decos, skills, free, cost, defense, score) -> "Found":
        f = cls.__new__(cls)
        f.pieces, f.talisman, f.decos, f.skills = pieces, talisman, decos, skills
        f.free, f.cost, f.defense, f.score = list(free), cost, defense, score
        return f

    def __init__(self, ainfo, tinfo, row):
        parts, tal, decos, skills, free, cost, defense, score = row
        self.pieces = [ainfo[k] if k is not None else None for k in parts]
        self.talisman = tinfo[tal] if tal is not None else None
        self.decos = decos
        self.skills = skills
        self.free = list(free)
        self.cost = cost
        self.defense = defense
        self.score = score
