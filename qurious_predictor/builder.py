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


def plan_paths(plan: dict) -> dict:
    """The roadmap of the saved sets (``Planner.plan``) as fixed paths per sequence: the pieces it
    augments in turn (segments) and the augments it keeps (reserved)."""
    armor = {}
    for q in plan["armor"]:
        segs, typed, owner, options = [], [], [], []
        for st in q["steps"]:
            if st.get("burnOn"):
                segs += [(st["burnOn"], st["augments"] - 1), (st["id"], 1)]
                typed += [(st["burnOn"], st["augments"] - 1, st["type"]), (st["id"], 1, st["type"])]
            else:
                segs.append((st["id"], st["augments"]))
                typed.append((st["id"], st["augments"], st["type"]))
            options += [(st["cost"], st["type"])] * st["augments"]
        for aid, k in segs:
            owner += [aid] * k
        armor[q["seed"]] = {"cost": q["cost"], "type": q["type"], "segments": segs, "owner": owner,
                            "typedSegments": typed, "options": options,
                            "reserved": [st["at"] for st in q["steps"]], "total": q["total"]}
    tals = {}
    for g in plan["talismans"]:
        tals[g["generator"]] = {"segments": [(st["method"], st["target"], st["talismans"]) for st in g["steps"]],
                                "reserved": [st["at"] for st in g["steps"]], "total": g["total"]}
    return {"armor": armor, "talismans": tals}


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
    exclude_armor: frozenset = frozenset()       # armor ids never used
    avoid_skills: frozenset = frozenset()        # no piece, talisman or decoration with these skills
    planned: list = field(default_factory=list)  # pieces and talismans saved sets will get: no new rolls
    # the saved sets' plan as fixed paths (see ``plan_paths``): new rolls on its sequences come from
    # inside it without changing it, or after it
    plan: dict | None = None
    # count only the rolls past the saved sets' plan on each of its sequences (what this set adds to
    # the plan of every saved set), not the rolls from now
    marginal: bool = False


class Builder:
    def __init__(self, data: dict, meld: melding.Tables):
        self.data = data
        self.meld = meld
        self.max_levels = {int(k): v + 1 for k, v in data["max_levels"].items()}
        self.decos = {d["id"]: d for d in data["decorations"]}

    # ---- candidates ------------------------------------------------------------------------------------
    def _armor_candidates(self, o: Options, box_armors, generators, owned_ids):
        """(candidate infos, per-part candidate tuples, streams of the sequences: see sets.rs ``Sync``)."""
        infos, parts = [], [[] for _ in range(5)]
        sync = None

        def add(part, info, skills, slots, defense, seq=-1, roll=0, stream=-1):
            skills = [(int(s), int(l)) for s, l in skills if l > 0]
            if str(info["id"]) in o.exclude_armor or any(s in o.avoid_skills for s, _ in skills):
                return
            info["key"] = len(infos)
            info["skills"] = skills
            info["slots"] = [int(x) for x in (list(slots) + [0, 0, 0])[:3]]
            info["defense"] = int(defense)
            infos.append(info)
            parts[part].append((info["key"], info["skills"], tuple(info["slots"]), int(defense), seq, roll, stream))

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
            weights = {int(k): float(v) for k, v in weights.items()}
            relevant = [s for s, _ in o.reqs]
            nt = search.native_tables(self.data)
            states = [g.state() for g in generators]
            paths = (o.plan or {}).get("armor") or {}
            # on a sequence the saved sets' plan uses, new rolls come after it (counted from its end) ...
            path_states = {}
            for seq, pa in paths.items():
                path_states[seq] = [states[seq]]
                for aid, k, ty in pa.get("typedSegments", [(a, k, pa["type"]) for a, k in pa["segments"]]):
                    segment = native().augment_path(nt, path_states[seq][-1], ty, [(*self._piece_args(aid), k)])
                    path_states[seq].extend(segment[1:])
                states[seq] = path_states[seq][-1]
            rows, lineage, split = native().augment_candidates(
                nt, pieces, states, list(engine.TYPE_NAMES), int(o.qurious_rolls), relevant, weights,
                [float(x) for x in o.slot_values])
            # after the plan: roll numbers (and where the streams split) count from now, plan included
            shifted = {}
            for aid, ty, n, skills, slots, ddef, res, delta, points, stream in rows:
                seq = engine.seed_index(self.data["armors"][str(aid)]["cost"], ty)
                if seq in paths:
                    shifted[stream] = paths[seq]["total"]
            for stream, after in shifted.items():
                if stream in lineage:
                    lineage[stream] = [(st + after if st else 0, g) for st, g in lineage[stream]]
            for seq, pa in paths.items():
                if seq in split:
                    split[seq] += pa["total"]
            sync = (lineage, split)
            for aid, ty, n, skills, slots, ddef, res, delta, points, stream in rows:
                a, full = self.data["armors"][str(aid)], self.data["all_armors"][str(aid)]
                seq = engine.seed_index(a["cost"], ty)
                after = paths[seq]["total"] if seq in paths else 0
                if after + n > o.qurious_rolls:
                    continue        # Qurious rolls caps the augments from now, the saved sets' plan included
                info = {"kind": "roll", "id": str(aid), "type": ty, "n": n, "pos": after + n, "seq": seq, "cost": a["cost"],
                        "after": after, "owned": aid in owned_ids, "def": ddef, "res": list(res),
                        "augments": [tuple(x) for x in delta], "slotPoints": points}
                add(full["part"], info, skills, slots, full.get("defMax", 0) + ddef, seq, after + n, stream)
            # ... or from inside it: an augment of the plan that goes on another piece without moving
            # the generator differently (the plan stays the same); its roll number is its place in the plan
            for seq, pa in paths.items():
                if len(set(pa.get("options", []))) > 1:
                    continue  # mixed routes remain fixed; new candidates are searched after them
                same = [x for x in pieces if self.data["armors"][str(x[0])]["cost"] == pa["cost"]]
                rows = native().path_candidates(nt, path_states[seq][:int(o.qurious_rolls) + 1], pa["reserved"], same,
                                                pa["type"], relevant,
                                                weights, [float(x) for x in o.slot_values])
                for aid, ty, k, skills, slots, ddef, res, delta, points, _ in rows:
                    full = self.data["all_armors"][str(aid)]
                    add(full["part"], {"kind": "roll", "id": str(aid), "type": ty, "n": k, "pos": k, "seq": seq, "cost": pa["cost"],
                                       "inPlan": True, "instead": pa["owner"][k - 1], "planTotal": pa["total"],
                                       "owned": aid in owned_ids, "def": ddef, "res": list(res),
                                       "augments": [tuple(x) for x in delta], "slotPoints": points},
                        skills, slots, full.get("defMax", 0) + ddef, seq, k, -1)
        for pl in o.planned:
            if pl["what"] != "armor":
                continue
            full = self.data["all_armors"].get(pl["id"])
            if full is None:
                continue
            levels = {sid: lv for sid, lv in full["skills"]}
            d, points, res, delta = pl["expected"]
            for sid, v in delta:
                levels[sid] = levels.get(sid, 0) + v
            base = _expand_slots(full["slots"])
            slots = apply_slot_bonus(base, points) if points else sorted(base, reverse=True)
            add(full["part"], {"kind": "planned", "id": pl["id"], "type": pl["type"], "n": pl["n"], "cost": pl["cost"],
                               "sets": pl["sets"], "owned": int(pl["id"]) in owned_ids, "def": d, "res": list(res),
                               "augments": [tuple(x) for x in delta], "slotPoints": points},
                levels.items(), slots, full.get("defMax", 0) + d)
        return infos, parts, sync

    def _piece_args(self, aid):
        a = self.data["armors"][str(aid)]
        return a["table"], a["cost"], [tuple(x) for x in a["skills"]]

    def _talisman_candidates(self, o: Options, box_talismans, generators):
        infos, cands = [], []

        def add(info, skills, slots, seq=-1, roll=0):
            if any(int(s) in o.avoid_skills for s, _ in skills):
                return
            info["key"] = len(infos)
            infos.append(info)
            cands.append((info["key"], [(int(s), int(l)) for s, l in skills], tuple(int(x) for x in slots), 0, seq, roll, -1))

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
            relevant = {s for s, _ in o.reqs}
            # melding generators the saved sets' plan uses: new talismans after it, or kept from it
            tpaths = (o.plan or {}).get("talismans") or {}
            states = [list(g.state()) for g in generators]
            for gen, pa in tpaths.items():
                tals_path, end = native().meld_path(nt, states[gen], pa["segments"])
                states[gen] = list(end)
                reserved = set(pa["reserved"])
                kept = []           # earliest first: a later talisman only if no kept one covers it
                k, segs = 0, [(m, tg) for m, tg, c in pa["segments"] for _ in range(c)]
                for (skills, slots, unsure), (m, tg) in zip(tals_path, segs):
                    k += 1
                    if k > o.talisman_rolls:
                        break
                    lv = [sum(l for sk, l in skills if sk == r) for r in sorted(relevant)]
                    caps = [sum(1 for x in slots if x >= L) for L in (1, 2, 3, 4)]
                    if k in reserved or not (any(lv) or slots[0]):
                        continue
                    if any(all(a >= b for a, b in zip(kl, lv)) and all(a >= b for a, b in zip(kc, caps)) for kl, kc in kept):
                        continue
                    kept.append((lv, caps))
                    add({"kind": "roll", "method": m, "target": tg, "n": k, "pos": k, "inPlan": True, "planTotal": pa["total"],
                         "unsure": unsure, "skills": [list(x) for x in skills], "slots": list(slots)},
                        skills, slots, TALISMAN_SEQ + gen, k)
            # Qurious Melding only: Vigor (random) and Cyclus with every skill it can pick
            jobs = [(m, row) for m in TALISMAN_METHODS
                    for row in (self.meld.targets(m) if m in melding.TARGETED else [None])]

            def run(job):
                m, row = job
                gen = melding.generator_index(m, row)
                return m, row, gen, native().meld_candidates(
                    nt, m, row.skill if row else None, states[gen], int(o.talisman_rolls),
                    [s for s, _ in o.reqs], weights, [float(x) for x in o.slot_values])

            with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
                results = list(pool.map(run, jobs))
            for m, row, gen, rows in results:
                for n, skills, slots, unsure in rows:
                    info = {"kind": "roll", "method": m, "target": row.skill if row else None, "n": n,
                            "unsure": unsure, "skills": [list(s) for s in skills], "slots": list(slots)}
                    after = tpaths[gen]["total"] if gen in tpaths else 0
                    if after + n > o.talisman_rolls:
                        continue
                    info.update(after=after, pos=after + n)
                    add(info, skills, slots, TALISMAN_SEQ + gen, after + n)
        for pl in o.planned:
            if pl["what"] == "talisman":
                add({"kind": "planned", "method": pl["method"], "target": pl["target"], "n": pl["n"], "sets": pl["sets"],
                     "unsure": False, "skills": [list(x) for x in pl["skills"]], "slots": list(pl["slots"])},
                    pl["skills"], pl["slots"])
        return infos, cands

    def _deco_tuples(self, o: Options, owned_decos):
        out = []
        for d in self.data["decorations"]:
            count = owned_decos.get(d["id"], 0) if o.owned_decos else NO_LIMIT
            if count and d["skill"] not in o.avoid_skills:
                out.append((d["id"], d["skill"], d["level"], d["points"], count))
        return out

    # ---- search ----------------------------------------------------------------------------------------
    def _common(self, o: Options, owned_decos):
        return ([int(x) for x in o.weapon], self._deco_tuples(o, owned_decos or {}),
                [(int(s), int(l)) for s, l in o.reqs], self.max_levels,
                {int(k): float(v) for k, v in o.weights.items()}, [float(x) for x in o.slot_values], o.value)

    def search(self, o: Options, box_armors=(), box_talismans=(), generators=None, owned_decos=None, on_search=None):
        """The best sets for ``o`` (fewest rolls first with ``cost_first``) and what was searched.
        ``on_search`` is called when the candidates are ready and the search itself starts."""
        owned_ids = {it.armor_id for it in box_armors}
        ainfo, parts, sync = self._armor_candidates(o, box_armors, generators, owned_ids)
        tinfo, tals = self._talisman_candidates(o, box_talismans, generators)
        if on_search:
            on_search()
        rows, complete = native().set_search(
            parts, tals, *self._common(o, owned_decos), bool(o.cost_first), int(min(o.max_cost, NO_LIMIT)),
            int(o.limit), float(o.seconds), float(o.floor), sync, self._base(o))
        counts = {"armor": [len(p) for p in parts], "talismans": len(tals), "complete": complete}
        return [Found(ainfo, tinfo, r) for r in rows], counts

    @staticmethod
    def _base(o: Options) -> dict | None:
        """With ``marginal``: per sequence, the rolls the saved sets' plan makes anyway."""
        if not (o.marginal and o.plan):
            return None
        base = {int(seq): int(pa["total"]) for seq, pa in (o.plan.get("armor") or {}).items()}
        base.update({TALISMAN_SEQ + int(gen): int(pa["total"]) for gen, pa in (o.plan.get("talismans") or {}).items()})
        return base

    def improve(self, o: Options, starts, box_armors=(), box_talismans=(), generators=None, owned_decos=None):
        """Pareto front (fewest rolls first, each next set worth more) of sets reached from ``starts`` by
        changing one or two parts at a time. ``starts`` = [(5 armor items or None, talisman item or None)]."""
        owned_ids = {it.armor_id for it in box_armors}
        ainfo, parts, sync = self._armor_candidates(o, box_armors, generators, owned_ids)
        tinfo, tals = self._talisman_candidates(o, box_talismans, generators)
        start_tuples = []
        for armor, talisman in starts:
            row = [self._talisman_start(tinfo, talisman)]
            row += [self._armor_start(ainfo, it) for it in armor]
            start_tuples.append(row)
        rows, complete = native().set_improve(
            parts, tals, *self._common(o, owned_decos), int(min(o.max_cost, NO_LIMIT)), int(o.limit),
            start_tuples, float(o.seconds), sync, self._base(o))
        counts = {"armor": [len(p) for p in parts], "talismans": len(tals), "complete": complete}
        return [Found(ainfo, tinfo, r) for r in rows], counts

    def best_and_improve(self, o: Options, current, box_armors=(), box_talismans=(), generators=None,
                         owned_decos=None):
        """Build optimizer: the best set without rolls (exact search, within a few seconds) and the front
        of improvements with rolls, from that set and from ``current`` (5 armor items, talisman item)."""
        base = Options(**{**o.__dict__, "qurious_rolls": 0, "talisman_rolls": 0, "cost_first": False, "limit": 1,
                          "seconds": min(o.seconds, 8.0), "max_cost": 0, "planned": []})
        best, counts0 = self.search(base, box_armors, box_talismans, generators, owned_decos)
        for f in best:
            f.tier = "owned"
        planned_best = []
        if o.planned:
            planned_best, c1 = self.search(Options(**{**base.__dict__, "planned": o.planned}),
                                           box_armors, box_talismans, generators, owned_decos)
            planned_best = [f for f in planned_best if not best or f.score > best[0].score
                            and any(p and p["kind"] == "planned" for p in [*f.pieces, f.talisman])]
            for f in planned_best:
                f.tier = "planned"
            counts0["complete"] = counts0["complete"] and c1["complete"]
        starts = [current] if current else []
        for f in best + planned_best:
            starts.append(([self._item(p) for p in f.pieces], self._tal_item(box_talismans, f.talisman)))
        if not starts:
            return best + planned_best, {**counts0, "proven": counts0["complete"]}
        front, counts = self.improve(o, starts, box_armors, box_talismans, generators, owned_decos)
        top = max((f.score for f in best + planned_best), default=float("-inf"))
        rolled = [f for f in front if f.score > top and has_rolls(f)]
        for f in rolled:
            f.tier = "rolls"
        if not best and not planned_best:
            zero = [f for f in front if not has_rolls(f)][:1]
            for f in zero:
                f.tier = "planned" if any(p and p["kind"] == "planned" for p in [*f.pieces, f.talisman]) else "owned"
            rolled = zero + rolled
        counts["proven"] = counts0["complete"]
        return best + planned_best + rolled, counts

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
        if info["kind"] == "planned":
            it = ArmorItem(int(info["id"]), True, defense=info.get("def", 0), resistances=list(info.get("res") or [0] * 5),
                           slot_points=info.get("slotPoints", 0), skills=list(info.get("augments") or []))
            it.planned = info
            return it
        return ArmorItem(int(info["id"]), False, resistances=[0] * 5, skills=[])

    @staticmethod
    def _tal_item(box_talismans, info):
        if info is not None and info["kind"] == "planned":
            from .savedata import TalismanItem
            it = TalismanItem([tuple(x) for x in info["skills"]], list(info["slots"]))
            it.planned = info
            return it
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
        planned = getattr(it, "planned", None)
        if planned:
            info.update(kind="planned", augmented=False, owned=planned.get("owned", False),
                        **{k: planned[k] for k in ("type", "n", "cost", "sets")})
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
        return (info["key"], info["skills"], tuple(info["slots"]), info["defense"], -1, 0, -1)

    @staticmethod
    def _talisman_start(tinfo, it):
        if it is None:
            return None
        info = {"kind": "owned", "box": it.index, "skills": list(it.skills), "slots": list(it.slots), "key": len(tinfo)}
        planned = getattr(it, "planned", None)
        if planned:
            info = {**planned, "key": len(tinfo)}
        tinfo.append(info)
        return (info["key"], [(int(s), int(l)) for s, l in it.skills], tuple(int(x) for x in it.slots), 0, -1, 0, -1)


def has_rolls(f) -> bool:
    """The set needs a new qurious augment or talisman (from inside the saved sets' plan or not)."""
    return any(p and p["kind"] == "roll" for p in [*f.pieces, f.talisman])


class Found:
    """One set from the search: (parts, talisman, decos, skills, free slots, cost, defense, score)."""

    @classmethod
    def of(cls, pieces, talisman, decos, skills, free, cost, defense, score) -> "Found":
        f = cls.__new__(cls)
        f.pieces, f.talisman, f.decos, f.skills = pieces, talisman, decos, skills
        f.free, f.cost, f.defense, f.score = list(free), cost, defense, score
        return f

    tier = None          # optimizer: "owned", "planned" (saved sets) or "rolls"

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
