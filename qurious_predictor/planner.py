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

import math

from . import engine, melding, search

FIND_LIMIT = 2_000_000          # augments or talismans searched per wanted result


class Stopped(Exception):
    """The app asked the running search to stop."""


MAX_ORDERS = 720                # orderings tried per sequence (6 wanted results); more: closest first


def _check_stop():
    if _native().search_progress()[3]:
        raise Stopped()


def best_order(start, targets, find):
    """The order of ``targets`` on one sequence that gets them all with the fewest rolls: [(target,
    rolls, state after)], or None when some does not come again. ``find(state, target, limit)`` ->
    (rolls, state after) or None. Branch and bound over the orders (closest first, a search never
    goes past the best total found); more than 6 targets: closest first only."""
    ts = sorted(targets, key=lambda t: t["n"])
    if math.factorial(len(ts)) > MAX_ORDERS:
        state, out = start, []
        for t in ts:
            f = find(state, t, FIND_LIMIT)
            if f is None:
                return None
            out.append((t, *f))
            state = f[1]
        return out
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
    return best[0]


def _native():
    if search._native is None:
        raise RuntimeError("The planner needs the compiled engine.")
    return search._native


def outcome_key(o) -> tuple:
    """(defense, slot points, resistances, sorted skill changes) as the engine reports an augment."""
    d, sl, res, sk = o
    return int(d), int(sl), tuple(int(x) for x in res), tuple(sorted((int(a), int(b)) for a, b in sk))


def targets_of(row: dict) -> dict:
    """The rolls a set from the Set builder needs (its pieces to augment and its talisman to meld)."""
    armor, talismans, craft = [], [], []
    for p in row.get("pieces") or []:
        if not p:
            continue
        if p["kind"] == "roll":
            q = p.get("qurious") or {}
            armor.append({"id": p["id"], "name": p["name"], "part": p["part"], "type": p["roll"]["type"],
                          "cost": p["roll"]["cost"], "n": p["roll"].get("pos", p["roll"]["n"]), "via": p["roll"].get("insteadId"),
                          "expected": [q.get("def", 0), q.get("slots", 0), list(q.get("res") or [0] * 5),
                                       sorted([s["id"], s["delta"]] for s in q.get("skills", []))]})
        elif p["kind"] == "game" and not p.get("owned"):
            craft.append({"id": p["id"], "name": p["name"]})
    t = row.get("talisman")
    if t and t["kind"] == "roll":
        slots = sorted((s["lv"] for s in (row.get("slots") or [[]] * 7)[6]), reverse=True)
        talismans.append({"method": t["method"], "target": t.get("target"), "n": t.get("pos", t["n"]),
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

    def armor_plan(self, targets, generators, box_armors) -> tuple[list, list]:
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
            others = sorted({x["id"] for x in ts} | {x["via"] for x in ts if x.get("via")})

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
                    lim = int(limit) if best is None else best[0] - 1
                    if lim <= 0:
                        break
                    f = _native().augment_find_via(nt, list(state), self._piece(b), (table, c, skills), ty, key, lim)
                    if f:
                        best = (*f, b)
                return best

            best = best_order(start, ts, find)
            if best is None:          # some augment does not come again: plan the others
                found = []
                for t in sorted(ts, key=lambda t: t["n"]):
                    f = find(start if not found else found[-1][2], t, FIND_LIMIT)
                    if f is None:
                        missing.append(t)
                    else:
                        found.append((t, *f))
                best = found
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
                              "total": done, "steps": rows, "zenny": zenny, "points": points,
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

            best = best_order(start, ts, find)
            if best is not None:
                best = [(t, k) for t, k, _ in best]
            if best is None:
                missing += ts
                continue
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
                           "total": done, "steps": rows, "kamura": kamura, "points": points, "used": used})
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

    def check(self, s: dict, generators, box_armors=()) -> dict:
        """A saved set against the save as it is now: whether its rolls still come in the order it was
        saved with (pieces of one sequence augmented one after the other), and what the planner needs."""
        nt = search.native_tables(self.data)
        in_order = True
        by_seq = {}
        for t in s["targets"]["armor"]:
            by_seq.setdefault((t["cost"], t["type"]), []).append(t)
        for (cost, ty), ts in by_seq.items():
            state, done = generators[engine.seed_index(cost, ty)].state(), 0
            for t in sorted(ts, key=lambda t: t["n"]):
                table, c, skills = self._piece(t["id"])
                state, last = _native().augment_advance(nt, list(state), table, c, skills, ty, t["n"] - done)
                done = t["n"]
                if last is None or outcome_key(last) != outcome_key(t["expected"]):
                    in_order = False
        plan = self.plan([s], generators, box_armors)
        saved = sum(max(t["n"] for t in ts) for ts in by_seq.values())
        return {"inOrder": in_order, "savedAugments": saved,
                "augments": plan["totals"]["augments"], "talismans": plan["totals"]["talismans"],
                "missing": len(plan["missing"]["armor"]) + len(plan["missing"]["talismans"]),
                "reordered": any(q["reordered"] for q in plan["armor"])}

    def plan(self, sets: list[dict], generators, box_armors) -> dict:
        armor_t, tal_t, craft = [], [], {}
        for s in sets:
            tg = s["targets"]
            for t in tg["armor"]:
                same = next((x for x in armor_t if x["id"] == t["id"] and outcome_key(x["expected"]) == outcome_key(t["expected"])
                             and x["type"] == t["type"]), None)
                if same:
                    same["sets"].append(s["name"])
                else:
                    armor_t.append({**t, "sets": [s["name"]]})
            for t in tg["talismans"]:
                same = next((x for x in tal_t if x["skills"] == t["skills"] and x["slots"] == t["slots"]
                             and x["method"] == t["method"] and x["target"] == t["target"]), None)
                if same:
                    same["sets"].append(s["name"])
                else:
                    tal_t.append({**t, "sets": [s["name"]]})
            for c in tg["craft"]:
                craft.setdefault(c["id"], {**c, "sets": []})["sets"].append(s["name"])
        # pieces augmented for more than one result need one copy each
        copies = {}
        for t in armor_t:
            copies[t["id"]] = copies.get(t["id"], 0) + 1
        armor, miss_a = self.armor_plan(armor_t, generators, box_armors)
        tals, miss_t = self.talisman_plan(tal_t, generators)
        amber = sum(s["points"] for s in armor)
        meld_pts = sum(g["points"] for g in tals)
        return {
            "armor": armor, "talismans": tals, "missing": {"armor": miss_a, "talismans": miss_t},
            "craft": list(craft.values()),
            "copies": [{"id": k, "count": v} for k, v in copies.items() if v > 1],
            "totals": {"zenny": sum(s["zenny"] for s in armor), "amber": amber, "augments": sum(s["total"] for s in armor),
                       "kamura": sum(g["kamura"] for g in tals), "meldPoints": meld_pts,
                       "talismansUsed": sum(g["used"] for g in tals), "talismans": sum(g["total"] for g in tals)},
            "materials": self.materials(amber, meld_pts),
        }
