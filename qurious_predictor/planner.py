"""Qurious and talisman planner: what to roll, in which order, to get every augment and talisman the
saved sets need, from the save as it is now, and what it costs.

How the generators move (see docs/RESEARCH.md):
* armor: one generator per augment cost (10, 12 ... 20) and option (Augment, Stability, Skills+,
  Slots+). An augment moves only its own generator, by a number of draws that depends on what it
  rolls and, sometimes, on the piece. So the planner walks each sequence with the pieces really
  augmented and looks for each wanted augment again from the current state.
* talismans: Qurious Melding—Vigor has one generator; Qurious Melding—Cyclus one per grade of the
  picked skill (every skill of that grade moves the same one).
"""

from __future__ import annotations

import json
import math

from . import engine, melding, search

FIND_LIMIT = 2_000_000          # augments or talismans searched per wanted result
# augments searched with the ones before a wanted result spent on another piece of the roadmap (a saved
# set's piece from inside the saved sets' plan): those come early; far ones are searched on the piece itself
VIA_LIMIT = 20_000


class Stopped(Exception):
    """The app asked the running search to stop."""


MAX_ORDERS = 720                # orderings tried per sequence (6 wanted results); more: closest first


def _check_stop():
    if _native().search_progress()[3]:
        raise Stopped()


def best_order(start, targets, find):
    """The order of ``targets`` on one sequence that gets them with the fewest rolls: ([(target, rolls,
    state after)], [targets that do not come again within FIND_LIMIT]). ``find(state, target, limit)``
    -> (rolls, state after) or None. Each target is first looked for once from ``start`` (the ones not
    found are left out, so no later step searches that far again). Then: branch and bound over the
    orders (closest first, a search never goes past the best total found); more than 6 targets: the
    next closest each time, trying them in the order they came from ``start`` (the closest is found
    first and bounds every other search)."""
    first, gone = {}, []
    for t in sorted(targets, key=lambda t: t["n"]):
        _check_stop()
        f = find(start, t, FIND_LIMIT)
        if f is None:
            gone.append(t)
        else:
            first[id(t)] = f[0]
    ts = sorted((t for t in targets if id(t) in first), key=lambda t: first[id(t)])

    def greedy():
        state, out, rest = start, [], ts
        while rest:
            _check_stop()
            near = None
            for i, t in enumerate(rest):
                lim = FIND_LIMIT if near is None else near[1][0] - 1
                if lim <= 0:
                    break
                f = find(state, t, lim)
                if f is not None:
                    near = (i, f)
                elif near is None:      # not even within FIND_LIMIT from here: it does not come again
                    gone.append(t)
            if near is None:
                break
            i, f = near
            out.append((rest[i], *f))
            state = f[1]
            rest = [t for j, t in enumerate(rest) if j != i and t not in gone]
        return out

    if math.factorial(len(ts)) > MAX_ORDERS:
        return greedy(), gone
    best = [None, math.inf]

    def rec(state, rest, steps, total):
        _check_stop()
        if not rest:
            if total < best[1]:
                best[0], best[1] = steps, total
            return
        for i, t in enumerate(rest):
            limit = FIND_LIMIT if best[0] is None else min(FIND_LIMIT, best[1] - total - 1)
            if limit <= 0:
                return
            f = find(state, t, limit)
            if f is not None:
                rec(f[1], rest[:i] + rest[i + 1:], steps + [(t, *f)], total + f[0])

    rec(start, ts, [], 0)
    return (best[0], gone) if best[0] is not None else (greedy(), gone)


def _native():
    if search._native is None:
        raise RuntimeError("The planner needs the compiled engine.")
    return search._native


def outcome_key(o) -> tuple:
    """(defense, slot points, resistances, sorted skill changes) as the engine reports an augment."""
    d, sl, res, sk = o
    return int(d), int(sl), tuple(int(x) for x in res), tuple(sorted((int(a), int(b)) for a, b in sk))


def targets_of(row: dict, skill_id=None) -> dict:
    """The rolls a set from the Set builder needs (its pieces to augment and its talisman to meld).
    A piece or talisman taken from another saved set's plan ("planned") is a roll of this set too: the
    plan keeps it whatever happens to that other set (changed, saved again or deleted); while the other
    set still wants the same result, both share one roll. ``skill_id``: skill name -> id, for talismans
    saved before the planned talisman kept its target skill's id."""
    armor, talismans, craft = [], [], []
    for p in row.get("pieces") or []:
        if not p:
            continue
        if p["kind"] in ("roll", "planned"):
            q = p.get("qurious") or {}
            r = p["roll"] if p["kind"] == "roll" else p["planned"]
            armor.append({"id": p["id"], "name": p["name"], "part": p["part"], "type": r["type"],
                          "cost": r["cost"], "n": r.get("pos", r["n"]), "via": r.get("insteadId"),
                          "expected": [q.get("def", 0), q.get("slots", 0), list(q.get("res") or [0] * 5),
                                       sorted([s["id"], s["delta"]] for s in q.get("skills", []))]})
        elif p["kind"] == "game" and not p.get("owned"):
            craft.append({"id": p["id"], "name": p["name"]})
    t = row.get("talisman")
    if t and t["kind"] in ("roll", "planned"):
        target = t.get("target")
        if target is None and t.get("targetName") and skill_id:
            target = skill_id(t["targetName"])
        slots = sorted((s["lv"] for s in (row.get("slots") or [[]] * 7)[6]), reverse=True)
        talismans.append({"method": t["method"], "target": target, "n": t.get("pos", t["n"]),
                          "skills": [[s["id"], s["level"]] for s in t["skills"]], "slots": (slots + [0, 0, 0])[:3]})
    return {"armor": armor, "talismans": talismans, "craft": craft}


class Planner:
    def __init__(self, data: dict, meld_tables: melding.Tables):
        self.data = data
        self.meld = meld_tables
        self.costs = data["costs"]

    # ---- armor ---------------------------------------------------------------------------------------
    def _piece(self, aid: str):
        a = self.data["armors"][aid]
        return a["table"], a["cost"], [tuple(s) for s in a["skills"]]

    def _rarity(self, aid: str) -> int:
        return self.data["all_armors"][aid]["rare"] + 1

    def _walk(self, state, order, ty):
        """Augment each wanted piece until its augment comes, in this order: [(target, augments)], state."""
        nt = search.native_tables(self.data)
        out = []
        for t in order:
            table, cost, skills = self._piece(t["id"])
            found = _native().augment_find(nt, list(state), table, cost, skills, ty, outcome_key(t["expected"]), FIND_LIMIT)
            if found is None:
                return None
            k, state = found
            out.append((t, k, state))
        return out

    def _cheap_burns(self, start, steps, ty, cheap):
        """Spend the augments before each wanted one on the cheapest piece of that cost, when that
        gives the same wanted augment (the draws are usually, not always, the same for every piece)."""
        if not cheap:
            return [None] * len(steps)
        nt = search.native_tables(self.data)
        state, out = start, []
        for t, k, end in steps:
            burn = None
            if k > 1 and self._rarity(cheap) < self._rarity(t["id"]):
                table, cost, skills = self._piece(cheap)
                mid, _ = _native().augment_advance(nt, list(state), table, cost, skills, ty, k - 1)
                table, cost, skills = self._piece(t["id"])
                after, last = _native().augment_advance(nt, list(mid), table, cost, skills, ty, 1)
                if last is not None and outcome_key(last) == outcome_key(t["expected"]) and tuple(after) == tuple(end):
                    burn = cheap
            out.append(burn)
            state = end
        return out

    def _armor_cost(self, aid: str, ty: int, count: int) -> tuple[int, int]:
        c = self.costs["armor"].get(str(self._rarity(aid)))
        if not c:
            return 0, 0
        return c["zenny"] * count, c["points"][str(ty)] * count

    def armor_plan(self, targets, generators, box_armors, rolled_targets=()) -> tuple[list, list]:
        """``rolled_targets``: results already in the box; their pieces can still take the augments before a
        wanted one (on another copy), as they did when the roadmap was first made."""
        groups = {}
        for t in targets:
            groups.setdefault((t["cost"], t["type"]), []).append(t)
        owned = {}
        for it in box_armors:
            a = self.data["armors"].get(str(it.armor_id))
            if a:
                owned.setdefault(a["cost"], set()).add(str(it.armor_id))
        sequences, missing = [], []
        for (cost, ty), ts in sorted(groups.items()):
            seq = engine.seed_index(cost, ty)
            start = generators[seq].state()
            nt = search.native_tables(self.data)
            others = sorted({x["id"] for x in ts} | {x["via"] for x in ts if x.get("via")}
                            | {x["id"] for x in rolled_targets if (x["cost"], x["type"]) == (cost, ty)})

            def find(state, t, limit, ty=ty):
                """The wanted augment with the augments before it on the piece itself or, when that is
                closer, on another piece of this roadmap (a set saved with an augment from inside the
                saved sets' plan needs the augments before it on the piece the plan spent them on)."""
                table, c, skills = self._piece(t["id"])
                key = outcome_key(t["expected"])
                best = _native().augment_find(nt, list(state), table, c, skills, ty, key, int(limit))
                best = (*best, None) if best else None
                for b in [t.get("via")] + [x for x in others if x != t.get("via")]:
                    if not b or b == t["id"]:
                        continue
                    lim = min(int(limit), VIA_LIMIT) if best is None else min(best[0] - 1, VIA_LIMIT)
                    if lim <= 0:
                        break
                    f = _native().augment_find_via(nt, list(state), self._piece(b), (table, c, skills), ty, key, lim)
                    if f:
                        best = (*f, b)
                return best

            best, gone = best_order(start, ts, find)
            missing += gone           # some augment does not come again: the others are planned
            if not best:
                continue
            cheap = min(owned.get(cost, ()), key=self._rarity, default=None)
            burns = self._cheap_burns(start, [(t, k, st) for t, k, st, _ in best], ty, cheap)
            burns = [via or b for (_, _, _, via), b in zip(best, burns)]
            rows, done, zenny, points = [], 0, 0, 0
            for (t, k, _, _), burn in zip(best, burns):
                done += k
                if burn:
                    z1, p1 = self._armor_cost(burn, ty, k - 1)
                    z2, p2 = self._armor_cost(t["id"], ty, 1)
                    z, pts = z1 + z2, p1 + p2
                else:
                    z, pts = self._armor_cost(t["id"], ty, k)
                zenny += z
                points += pts
                rows.append({**t, "augments": k, "at": done, "burnOn": burn, "zenny": z, "points": pts})
            order_changed = [r["id"] for r in rows] != [t["id"] for t in sorted(ts, key=lambda t: t["n"])]
            sequences.append({"cost": cost, "type": ty, "typeName": engine.TYPE_NAMES[ty], "seed": seq,
                              "start": list(start), "total": done, "steps": rows, "zenny": zenny, "points": points,
                              "reordered": order_changed and len(rows) > 1})
        return sequences, missing

    # ---- talismans -----------------------------------------------------------------------------------
    def talisman_plan(self, targets, generators) -> tuple[list, list]:
        nt = melding.native_tables(self.data["melding"])
        rows_by = {}
        for t in targets:
            row = next((r for r in self.meld.targets(t["method"]) if r.skill == t["target"]), None) if t["target"] else None
            gen = melding.generator_index(t["method"], row)
            rows_by.setdefault(gen, []).append(t)
        groups, missing = [], []
        for gen, ts in sorted(rows_by.items()):
            start = generators[gen].state()
            def find(state, t, limit):
                return _native().meld_find(nt, t["method"], t["target"], list(state),
                                           [tuple(s) for s in t["skills"]], list(t["slots"]), int(limit))

            best, gone = best_order(start, ts, find)
            missing += gone
            if not best:
                continue
            best = [(t, k) for t, k, _ in best]
            m = self.costs["melding"]
            rows, done, kamura, points, used = [], 0, 0, 0, 0
            for t, k in best:
                c = m[str(t["method"])]
                done += k
                kamura += c["kamura"] * k
                points += c["points"] * k
                used += c["talismans"] * k
                rows.append({**t, "talismans": k, "at": done})
            method = best[0][0]["method"]
            grade = None if gen == melding.GENERATOR.get(10) else gen - melding.CYCLUS_GENERATOR
            groups.append({"generator": gen, "method": method, "methodName": melding.METHODS[method], "grade": grade,
                           "start": list(start), "total": done, "steps": rows, "kamura": kamura, "points": points, "used": used})
        return groups, missing

    # ---- materials -----------------------------------------------------------------------------------
    def materials(self, amber_points: int, meld_points: int) -> dict:
        items = self.costs["items"]
        cat = next(iter(self.costs["armor"].values()))["category"] if self.costs["armor"] else None
        amber = sorted(((i, v) for i, v in items.items() if cat in v["categories"] and v["worth"]),
                       key=lambda e: -e[1]["worth"])
        usable = set(self.costs["melding"].get("10", {}).get("items", []))
        meld = sorted(((i, v) for i, v in items.items() if int(i) in usable and v["meldPoints"]),
                      key=lambda e: -e[1]["meldPoints"])
        return {
            "amber": [{"id": i, "names": v["names"], "worth": v["worth"], "count": math.ceil(amber_points / v["worth"])}
                      for i, v in amber] if amber_points else [],
            "meld": [{"id": i, "names": v["names"], "worth": v["meldPoints"], "count": math.ceil(meld_points / v["meldPoints"])}
                     for i, v in meld] if meld_points else [],
            "mix": self._mix(amber_points, [v["worth"] for _, v in amber]),
        }

    @staticmethod
    def _mix(points: int, worths: list) -> list:
        """Fewest items that pay `points`: as many of the biggest as fit, then the next..."""
        out, left = [], points
        for w in sorted(set(worths), reverse=True):
            n = left // w
            out.append(n)
            left -= n * w
        if left > 0 and out:
            out[-1] += 1
        return out

    def check(self, s: dict, generators, box_armors=(), together: dict | None = None, box_talismans=()) -> dict:
        """A saved set against the save as it is now: whether its rolls still come in the order it was
        saved with (pieces of one sequence augmented one after the other), and what the planner needs.
        ``together``: the roadmap of every saved set (``plan``); a set saved with pieces inside or after
        that roadmap needs it, so its augments are counted along it (up to its last piece on each
        sequence, the other sets' pieces before that included)."""
        nt = search.native_tables(self.data)
        in_order = True
        by_seq = {}
        rolled = self.rolled(box_armors, box_talismans)
        for t in s["targets"]["armor"]:
            if not self.is_rolled(t, rolled):        # already in the box: done
                by_seq.setdefault((t["cost"], t["type"]), []).append(t)
        for (cost, ty), ts in by_seq.items():
            state, done = generators[engine.seed_index(cost, ty)].state(), 0
            for t in sorted(ts, key=lambda t: t["n"]):
                table, c, skills = self._piece(t["id"])
                state, last = _native().augment_advance(nt, list(state), table, c, skills, ty, t["n"] - done)
                done = t["n"]
                if last is None or outcome_key(last) != outcome_key(t["expected"]):
                    in_order = False
        saved = sum(max(t["n"] for t in ts) for ts in by_seq.values())
        if together is not None:
            return self._check_together(s, together, in_order, saved)
        plan = self.plan([s], generators, box_armors, box_talismans)
        return {"inOrder": in_order, "savedAugments": saved, "done": len(plan["done"]),
                "augments": plan["totals"]["augments"], "talismans": plan["totals"]["talismans"],
                "missing": len(plan["missing"]["armor"]) + len(plan["missing"]["talismans"]),
                "reordered": any(q["reordered"] for q in plan["armor"])}

    @staticmethod
    def _check_together(s: dict, plan: dict, in_order: bool, saved: int) -> dict:
        tg = s["targets"]
        mine_a = {(t["id"], t["type"], outcome_key(t["expected"])) for t in tg["armor"]}
        mine_t = {(t["method"], t["target"], json.dumps(t["skills"]), json.dumps(t["slots"])) for t in tg["talismans"]}
        augments = sum(max((st["at"] for st in q["steps"] if (st["id"], st["type"], outcome_key(st["expected"])) in mine_a),
                           default=0) for q in plan["armor"])
        talismans = sum(max((st["at"] for st in g["steps"]
                             if (st["method"], st["target"], json.dumps(st["skills"]), json.dumps(st["slots"])) in mine_t),
                            default=0) for g in plan["talismans"])
        missing = (sum((t["id"], t["type"], outcome_key(t["expected"])) in mine_a for t in plan["missing"]["armor"])
                   + sum((t["method"], t["target"], json.dumps(t["skills"]), json.dumps(t["slots"])) in mine_t
                         for t in plan["missing"]["talismans"]))
        reordered = any(q["reordered"] and any((st["id"], st["type"], outcome_key(st["expected"])) in mine_a for st in q["steps"])
                        for q in plan["armor"])
        done = sum(1 for d in plan.get("done", []) if s["name"] in d["sets"])
        return {"inOrder": in_order, "savedAugments": saved, "augments": augments, "talismans": talismans,
                "missing": missing, "reordered": reordered, "together": True, "done": done}

    def progress(self, plan: dict, generators, box_armors=(), box_talismans=()) -> dict:
        """How far each sequence of a plan made earlier has come in the save as it is now, without
        planning again: the generator now is looked for along the plan's own route (every augment or
        meld of it, from the state the plan started at). Found after n augments: the steps up to n are
        done. Not found: something else moved that sequence, the rest of the plan no longer holds.
        Fills ``progress`` on every sequence and ``done`` / ``inBox`` / ``doneHere`` on every step."""
        nt = search.native_tables(self.data)
        rolled = self.rolled(box_armors, box_talismans)
        done_all = left_all = 0
        off = 0
        for q in plan["armor"]:
            segs = []
            for st in q["steps"]:
                k = st["augments"]
                if st.get("burnOn") and k > 1:
                    segs += [(*self._piece(st["burnOn"]), k - 1), (*self._piece(st["id"]), 1)]
                else:
                    segs.append((*self._piece(st["id"]), k))
            states = [tuple(x) for x in _native().augment_path(nt, list(q["start"]), q["type"], segs)]
            self._burn_checks(q, states, nt, box_armors)
            now = tuple(generators[q["seed"]].state())
            n = states.index(now) if now in states else None
            self._mark(q, n, lambda st: self.is_rolled(st, rolled))
            off += n is None
            done_all += n or 0
            left_all += q["total"] - (n or 0)
        mt = melding.native_tables(self.data["melding"])
        for g in plan["talismans"]:
            # the state after every meld of the route (each step melded in one go, as the plan says)
            states, state = [tuple(g["start"])], list(g["start"])
            for st in g["steps"]:
                for j in range(1, st["talismans"] + 1):
                    _, after = _native().meld_path(mt, list(state), [(st["method"], st["target"], j)])
                    states.append(tuple(after))
                state = list(states[-1])
            now = tuple(generators[g["generator"]].state())
            n = states.index(now) if now in states else None
            self._mark(g, n, lambda st: self.is_rolled(st, rolled, True), "talismans")
            off += n is None
        plan["progress"] = {"augmentsDone": done_all, "augmentsLeft": left_all, "offRoute": off}
        return plan

    def _burn_checks(self, q: dict, states: list, nt, box_armors=()):
        """For a step whose augments before the wanted one go on another piece: what that piece's last
        of them gives (to check you are where the plan is before the augment that counts), and the other
        pieces that can take them instead. How many draws an augment takes depends on the piece (its own
        skills), not on its rarity, so only the pieces whose augments end at the same place work."""
        owned = {str(it.armor_id) for it in box_armors}
        for st in q["steps"]:
            k = st["augments"]
            if not st.get("burnOn") or k < 2:
                continue
            s0, end = list(states[st["at"] - k]), states[st["at"]]
            _, st["burnLast"] = _native().augment_advance(nt, s0, *self._piece(st["burnOn"]), q["type"], k - 1)
            also, seen = [], {st["burnOn"], st["id"]}
            for aid, a in self.data["armors"].items():
                if a["cost"] != q["cost"] or aid in seen:
                    continue
                mid, _ = _native().augment_advance(nt, s0, *self._piece(aid), q["type"], k - 1)
                after, _ = _native().augment_advance(nt, list(mid), *self._piece(st["id"]), q["type"], 1)
                if tuple(after) == end:
                    also.append(aid)
            # the ones in your box first, then the cheapest
            st["burnAlso"] = sorted(also, key=lambda x: (x not in owned, self._rarity(x), x))

    @staticmethod
    def _mark(q: dict, n, in_box, size: str = "augments"):
        q["progress"] = {"done": n, "onRoute": n is not None,
                         "finished": n is not None and n >= q["total"]}
        for st in q["steps"]:
            first = st["at"] - st[size]
            st["done"] = n is not None and n >= st["at"]
            st["inBox"] = bool(in_box(st))
            st["doneHere"] = max(0, n - first) if n is not None and first < n < st["at"] else 0

    @staticmethod
    def rolled(box_armors=(), box_talismans=()) -> tuple[set, set]:
        """The results already in the equipment box: armor (id, outcome key) and talismans (skills,
        slots). A saved set's result found there is done: the plan does not look for it again."""
        armor = set()
        for it in box_armors:
            if not getattr(it, "augmented", False):
                continue
            sk = {}
            for s, v in it.skills or []:
                sk[s] = sk.get(s, 0) + v
            armor.add((str(it.armor_id), outcome_key([it.defense, it.slot_points, it.resistances or [0] * 5,
                                                      [[s, v] for s, v in sk.items() if v]])))
        tals = {(json.dumps(sorted([int(s), int(l)] for s, l in t.skills)), json.dumps(sorted(t.slots, reverse=True)))
                for t in box_talismans}
        return armor, tals

    @staticmethod
    def is_rolled(t: dict, rolled: tuple[set, set], talisman: bool = False) -> bool:
        if talisman:
            return (json.dumps(sorted([int(s), int(l)] for s, l in t["skills"])),
                    json.dumps(sorted(t["slots"], reverse=True))) in rolled[1]
        return (t["id"], outcome_key(t["expected"])) in rolled[0]

    def plan(self, sets: list[dict], generators, box_armors, box_talismans=()) -> dict:
        armor_t, tal_t, craft, done = [], [], {}, []
        rolled = self.rolled(box_armors, box_talismans)
        for s in sets:
            tg = s["targets"]
            for t in tg["armor"] + tg["talismans"]:
                tal = "method" in t
                if self.is_rolled(t, rolled, tal):
                    same = next((d for d in done if d["target"] == t), None)
                    if same:
                        same["sets"].append(s["name"])
                    else:
                        done.append({"target": t, "talisman": tal, "sets": [s["name"]]})
            for t in tg["armor"]:
                if self.is_rolled(t, rolled):
                    continue
                same = next((x for x in armor_t if x["id"] == t["id"] and outcome_key(x["expected"]) == outcome_key(t["expected"])
                             and x["type"] == t["type"]), None)
                if same:
                    same["sets"].append(s["name"])
                else:
                    armor_t.append({**t, "sets": [s["name"]]})
            for t in tg["talismans"]:
                if self.is_rolled(t, rolled, True):
                    continue
                same = next((x for x in tal_t if x["skills"] == t["skills"] and x["slots"] == t["slots"]
                             and x["method"] == t["method"] and x["target"] == t["target"]), None)
                if same:
                    same["sets"].append(s["name"])
                else:
                    tal_t.append({**t, "sets": [s["name"]]})
            for c in tg["craft"]:
                craft.setdefault(c["id"], {**c, "sets": []})["sets"].append(s["name"])
        armor, miss_a = self.armor_plan(armor_t, generators, box_armors,
                                        [d["target"] for d in done if not d["talisman"]])
        tals, miss_t = self.talisman_plan(tal_t, generators)
        amber = sum(s["points"] for s in armor)
        meld_pts = sum(g["points"] for g in tals)
        # every piece is augmented on a new copy, so the pieces in the box are never touched: one copy
        # per result kept on it, and one more for a piece that takes the augments before another
        # piece's result (its own result is thrown away each time)
        new = {}
        for q in armor:
            for st in q["steps"]:
                c = new.setdefault(st["id"], {"id": st["id"], "name": st["name"], "keep": 0, "burn": 0, "sets": []})
                c["keep"] += 1
                c["sets"] += [n for n in st["sets"] if n not in c["sets"]]
                if st["burnOn"]:
                    b = new.setdefault(st["burnOn"], {"id": st["burnOn"], "name": None, "keep": 0, "burn": 0, "sets": []})
                    b["burn"] = 1
        for c in new.values():
            c["count"] = c["keep"] + c["burn"]
        return {
            "armor": armor, "talismans": tals, "missing": {"armor": miss_a, "talismans": miss_t},
            "craft": list(craft.values()), "done": done, "newCopies": list(new.values()),
            "totals": {"zenny": sum(s["zenny"] for s in armor), "amber": amber, "augments": sum(s["total"] for s in armor),
                       "kamura": sum(g["kamura"] for g in tals), "meldPoints": meld_pts,
                       "talismansUsed": sum(g["used"] for g in tals), "talismans": sum(g["total"] for g in tals)},
            "materials": self.materials(amber, meld_pts),
        }
