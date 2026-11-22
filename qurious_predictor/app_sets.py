"""App API of the Set builder, the build optimizer and the export (mixed into ``app.Api``)."""

from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path

from mhrise_exporter.export import Names, _expand_slots, apply_slot_bonus, qurious_lines, talisman_lines

from . import builder, engine, melding, planner

MAX_ROLLS = 2**31 - 1          # no practical limit: the engine runs them in Rust
MAX_RESULTS = 1000
OWNER_NAMES = ["Weapon", "Head", "Chest", "Arms", "Waist", "Legs", "Talisman"]
EXPORTS = {
    # kind: (label, formats)
    "talismans": ("Talismans", ["wikidb", "csv", "json"]),
    "qurious": ("Qurious armor", ["wikidb", "csv", "json"]),
    "armor": ("All armor", ["csv", "json"]),
    "decorations": ("Decorations", ["csv", "json"]),
    "everything": ("Everything", ["json"]),
}
FILE_NAMES = {("talismans", "wikidb"): "ExportedTalismans.txt", ("qurious", "wikidb"): "ExportedQuriousArmors.txt"}


def _rolls(v) -> int:
    try:
        return max(0, min(MAX_ROLLS, int(v or 0)))
    except (TypeError, ValueError):
        return 0


def _csv_row(kind: str, r: dict) -> dict:
    """One CSV line: a column per value."""
    if kind == "talismans":
        sk = r["skills"] + [{"name": "", "level": ""}] * 2
        return {"Skill 1": sk[0]["name"], "Level 1": sk[0]["level"], "Skill 2": sk[1]["name"], "Level 2": sk[1]["level"],
                "Slot 1": r["slots"][0], "Slot 2": r["slots"][1], "Slot 3": r["slots"][2]}
    if kind == "decorations":
        return {"Decoration": r["name"], "Skill": r["skill"], "Points": r["points"], "Slot level": r["slotLevel"],
                "Owned": r["owned"]}
    res = r["resistances"]
    return {"Part": r["part"], "Armor": r["name"], "Rarity": r["rarity"], "Qurious": "yes" if r["qurious"] else "",
            "Defense": r["defense"], "Qurious defense": r["defenseChange"], "Fire": res[0], "Water": res[1],
            "Thunder": res[2], "Ice": res[3], "Dragon": res[4], "Slot 1": r["slots"][0], "Slot 2": r["slots"][1],
            "Slot 3": r["slots"][2], "Skills": "; ".join(f"{x['name']} {x['level']}" for x in r["skills"])}


class SetsMixin:
    """Needs from ``Api``: data, box, generators, melding, save_file, owned_decos, loadout_list,
    box_weapons, _lock, _name, _skill, _talisman_scorer."""

    # ---- shared ------------------------------------------------------------------------------------
    def _builder(self) -> builder.Builder:
        if getattr(self, "_builder_obj", None) is None or self._builder_obj.data is not self.data:
            self._builder_obj = builder.Builder(self.data, self.melding)
        return self._builder_obj

    def _preset_values(self, preset):
        scorer = self._talisman_scorer(preset)
        return scorer.weights, list(scorer.slot_values)

    def _deco_name(self, did: int) -> str:
        d = self._builder().decos.get(did)
        return self._name(d["names"]) if d else f"#{did}"

    def builder_info(self):
        """Skills with the decoration level that gives them, owned decorations, loadouts."""
        if not self.data:
            return {"error": "Game data not loaded."}
        deco_lv = {}
        for d in self.data["decorations"]:
            deco_lv[d["skill"]] = min(deco_lv.get(d["skill"], 9), d["level"])
        skills = sorted((dict(self._skill(int(k)), deco=deco_lv.get(int(k))) for k in self.data["skills"]),
                        key=lambda s: s["name"].lower())
        armors = sorted(({"id": aid, "name": self._name(a["names"]), "part": a["part"], "rarity": a["rare"] + 1}
                         for aid, a in self.data["all_armors"].items() if a["names"]), key=lambda a: (-a["rarity"], a["name"]))
        return {"skills": skills, "armors": armors,
                "loadouts": [{"key": i, "name": l.name} for i, l in enumerate(self.loadout_list)],
                "decorations": sum(self.owned_decos.values()), "maxRolls": MAX_ROLLS}

    def _options(self, p: dict, **extra) -> builder.Options:
        weights, slot_values = self._preset_values(p.get("preset"))
        ranks = tuple(r for r in (p.get("ranks") or ["master"]) if r in builder.RANKS) or ("master",)
        return builder.Options(
            reqs=[(int(w["id"]), int(w.get("level") or 1)) for w in p.get("skills") or []],
            weapon=[max(0, min(4, int(x or 0))) for x in (p.get("weapon") or [0, 0, 0])][:3],
            ranks=ranks,
            game_armor=bool(p.get("gameArmor", True)),
            owned_armor=bool(p.get("ownedArmor", True)),
            owned_talismans=bool(p.get("ownedTalismans", True)),
            qurious_rolls=_rolls(p.get("quriousRolls")),
            qurious_owned_only=bool(p.get("quriousOwnedOnly", False)),
            talisman_rolls=_rolls(p.get("talismanRolls")),
            owned_decos=bool(p.get("ownedDecos", False)),
            exclude_armor=frozenset(str(x) for x in p.get("excludeArmor") or []),
            avoid_skills=frozenset(int(x) for x in p.get("avoidSkills") or []),
            marginal=bool(p.get("marginal", False)),
            weights=weights, slot_values=slot_values, **extra)

    # ---- set rows ----------------------------------------------------------------------------------
    def _armor_name(self, aid) -> str:
        a = self.data["all_armors"].get(str(aid))
        return self._name(a["names"]) if a and a["names"] else f"#{aid}"

    def _set_row(self, f: builder.Found, reqs=(), base=None) -> dict:
        """A set for the app: pieces, talisman, decorations in their slots, skills, totals and what to do."""
        wanted = dict(reqs)
        slots = {o: [] for o in range(7)}
        slots[0] = [{"lv": lv, "deco": None} for lv in self._weapon if lv]
        pieces = []
        res = [0] * 5
        for part, info in enumerate(f.pieces):
            if info is None:
                pieces.append(None)
                continue
            a = self.data["all_armors"][info["id"]]
            base_slots = (sorted(_expand_slots(a["slots"]), reverse=True) + [0, 0, 0])[:3]
            r = [x + y for x, y in zip(a.get("res", [0] * 5), info.get("res") or [0] * 5)]
            res = [x + y for x, y in zip(res, r)]
            slots[part + 1] = [{"lv": lv, "up": lv > b, "deco": None} for lv, b in zip(info["slots"], base_slots) if lv]
            row = {"part": part, "id": info["id"], "name": self._name(a["names"]), "rarity": a["rare"] + 1,
                   "kind": info["kind"], "owned": bool(info.get("owned")), "augmented": bool(info.get("augmented")),
                   "def": info["defense"], "res": r,
                   "skills": [dict(self._skill(s), level=l) for s, l in info["skills"]]}
            if info["kind"] == "roll":
                row["roll"] = {"type": info["type"], "typeName": engine.TYPE_NAMES[info["type"]], "n": info["n"],
                               "cost": info["cost"], "seq": info["seq"], "after": info.get("after", 0), "pos": info.get("pos", info["n"]),
                               "inPlan": bool(info.get("inPlan")),
                               "instead": self._armor_name(info["instead"]) if info.get("instead") else None,
                               "insteadId": info.get("instead")}
            if info["kind"] == "planned":
                row["planned"] = {"type": info["type"], "typeName": engine.TYPE_NAMES[info["type"]], "n": info["n"],
                                  "cost": info["cost"], "sets": info["sets"]}
            if info["kind"] in ("roll", "planned") or info.get("augmented"):
                row["qurious"] = self._qurious(info)
            pieces.append(row)
        tal = None
        if f.talisman:
            t = f.talisman
            slots[6] = [{"lv": lv, "deco": None} for lv in t["slots"] if lv]
            tal = {"kind": t["kind"], "skills": [dict(self._skill(s), level=l) for s, l in t["skills"]]}
            if t["kind"] == "roll":
                tal.update(method=t["method"], methodName=melding.METHODS[t["method"]], n=t["n"],
                           target=t["target"], targetName=self._skill(t["target"])["name"] if t["target"] else None,
                           unsure=t["unsure"], after=t.get("after", 0), inPlan=bool(t.get("inPlan")), pos=t.get("pos", t["n"]))
            if t["kind"] == "planned":
                tal.update(method=t["method"], methodName=melding.METHODS[t["method"]], n=t["n"], sets=t["sets"],
                           targetName=self._skill(t["target"])["name"] if t["target"] else None)
        for owner, k, did, extra in f.decos:
            if k < len(slots[owner]):
                d = self._builder().decos.get(did, {})
                slots[owner][k]["deco"] = {"id": did, "name": self._deco_name(did), "level": d.get("level", 0),
                                           "skill": d.get("skill"), "extra": bool(extra)}
        skills = [dict(self._skill(s), level=l, wanted=wanted.get(s, 0)) for s, l in f.skills]
        skills.sort(key=lambda s: (-(s["wanted"] > 0), -s["level"], s["name"]))
        n_qur = sum(1 for p in pieces if p and p["kind"] == "roll")
        return {
            "cost": f.cost, "defense": f.defense, "score": f.score, "res": res,
            "gain": round(f.score - base, 2) if base is not None else None,
            "pieces": pieces, "talisman": tal, "slots": [slots[o] for o in range(7)],
            "skills": skills, "free": f.free,
            "rolls": {"qurious": sum(self._seq_tops(f)),
                      "talisman": f.talisman.get("pos", f.talisman["n"]) if f.talisman and f.talisman["kind"] == "roll" else 0,
                      "pieces": n_qur},
            "steps": self._steps(f),
            "tier": f.tier,
        }

    def _qurious(self, info) -> dict:
        """What qurious crafting changes on a piece: skill levels, slot points, defense, resistances."""
        total = {}
        for sid, v in info.get("augments") or []:
            total[sid] = total.get(sid, 0) + v
        return {"skills": [dict(self._skill(sid), delta=v) for sid, v in total.items() if v],
                "slots": info.get("slotPoints", 0), "def": info.get("def", 0), "res": list(info.get("res") or [0] * 5)}

    @staticmethod
    def _seq_tops(f: builder.Found) -> list[int]:
        tops = {}
        for p in f.pieces:
            if p and p["kind"] == "roll":
                tops[p["seq"]] = max(tops.get(p["seq"], 0), p.get("pos", p["n"]))
        return list(tops.values())

    def _steps(self, f: builder.Found) -> list[str]:
        """What to do in game, in order."""
        steps = []
        for p in f.pieces:
            if p and p["kind"] == "game" and not p.get("owned"):
                steps.append(f"Craft {self._armor_name(p['id'])}.")
        planned = sorted({s for p in [*f.pieces, f.talisman] if p and p["kind"] == "planned" for s in p["sets"]})
        if planned:
            steps.append(f"Pieces planned by the saved set{'s' if len(planned) > 1 else ''} {', '.join(planned)}: "
                         "make them as Saved sets & planner says.")
        groups = {}
        for p in f.pieces:
            if p and p["kind"] == "roll":
                if not p.get("owned"):
                    steps.append(f"Craft {self._armor_name(p['id'])} (a fresh copy, without augments).")
                if p.get("inPlan"):
                    steps.append(f"{engine.TYPE_NAMES[p['type']]} on cost {p['cost']} armor, while following the saved "
                                 f"sets' plan (Saved sets & planner): its augment #{p['n']}, which the plan spends on "
                                 f"{self._armor_name(p['instead'])}, goes on {self._armor_name(p['id'])} instead: keep it. "
                                 f"The generator ends at the same place, so the rest of the plan stays the same.")
                else:
                    groups.setdefault(p["seq"], []).append(p)
        for seq, ps in groups.items():
            ps.sort(key=lambda p: p["n"])
            top = ps[-1]["n"]
            after = ps[0].get("after", 0)
            fresh = " (each on a copy without augments)" if any(p.get("augmented") or p.get("owned") for p in ps) else ""
            done, parts = 0, []
            for p in ps:
                k = p["n"] - done
                parts.append(f"{'augment' if not done else 'then'} {self._armor_name(p['id'])} {k} time{'s' if k > 1 else ''}"
                             f" and keep the last (#{p['n']})")
                done = p["n"]
            first = (f"first finish the saved sets' plan on this sequence ({after:,} augments, Saved sets & planner), "
                     f"then " if after else "")
            steps.append(f"{engine.TYPE_NAMES[ps[0]['type']]} on cost {ps[0]['cost']} armor, {top} augment{'s' if top > 1 else ''} "
                         f"in this order{fresh}: {first}{'; '.join(parts)}. Augmenting another piece in between can change "
                         f"what comes next.")
        t = f.talisman
        if t and t["kind"] == "roll":
            pick = f", picking {self._skill(t['target'])['name']}" if t["target"] else ""
            if t.get("inPlan"):
                steps.append(f"{melding.METHODS[t['method']]}{pick}: talisman #{t['n']} of the saved sets' plan (one it "
                             f"melds on the way): keep it.")
            else:
                after = t.get("after", 0)
                first = (f"after the saved sets' plan on this melding sequence ({after:,} talismans), " if after else "")
                steps.append(f"{melding.METHODS[t['method']]}{pick}: {first}talisman #{t['n']} "
                             f"({t['n'] - 1} talisman{'s' if t['n'] != 2 else ''} of this method before it, any materials)."
                             + (" Its second skill may differ: Cyclus re-picks it with a generator the save does not keep."
                                if t["unsure"] else ""))
        if any(p and p["kind"] == "roll" for p in f.pieces) or (t and t["kind"] == "roll"):
            steps.append("Rolls are counted from the save as it is now; after each step, save in game and press Reload save.")
        return steps

    # ---- progress and stop (called while a search runs: no lock) --------------------------------------
    def _search_begin(self, phase: str):
        builder.native().search_reset()
        self._progress = {"phase": phase, "t0": time.time()}

    def _search_phase(self, phase: str, **extra):
        self._progress = {**getattr(self, "_progress", {"t0": time.time()}), "phase": phase, **extra}

    def search_progress(self):
        """What the running Set builder / optimizer search is doing, for the progress line."""
        pr = getattr(self, "_progress", None)
        if not pr:
            return {"phase": None}
        rolls, nodes, budget, stop = builder.native().search_progress()
        return {"phase": pr.get("phase"), "rolls": rolls, "rollsTotal": pr.get("rollsTotal", 0), "nodes": nodes,
                "budget": budget, "stopping": stop, "seconds": round(time.time() - pr["t0"], 1)}

    def search_stop(self):
        """Stop the running search: it returns the sets it found so far."""
        builder.native().search_cancel()
        return True

    def _stopped(self) -> bool:
        return builder.native().search_progress()[3]

    # ---- saved sets' pieces --------------------------------------------------------------------------
    def _saved_plan(self) -> dict | None:
        """The roadmap of every saved set together (``Planner.plan``), cached per save state."""
        sets = self.saved_sets()
        if not sets or not self.generators:
            return None
        key = (json.dumps([x["targets"] for x in sets], sort_keys=True, default=str),
               tuple(tuple(g.state()) for g in self.generators))
        cache = getattr(self, "_plan_cache", None)
        if cache and cache[0] == key:
            return cache[1]
        plan = planner.Planner(self.data, self.melding).plan(sets, self.generators, self.box[0], self.box[1])
        self._plan_cache = (key, plan)
        return plan

    def _planned_pieces(self) -> tuple[list[dict], dict | None]:
        """The pieces and talismans every saved set will get, each with how far along the saved sets'
        roadmap it comes (``n``), and that roadmap as fixed paths for the new rolls (``builder.plan_paths``)."""
        try:
            plan = self._saved_plan()
        except planner.Stopped:
            return [], None
        if not plan:
            return [], None
        out = []
        for q in plan["armor"]:
            for st in q["steps"]:
                out.append({k: v for k, v in st.items() if k not in ("augments", "at", "burnOn", "zenny", "points")}
                           | {"what": "armor", "n": st["at"]})
        for g in plan["talismans"]:
            for st in g["steps"]:
                out.append({k: v for k, v in st.items() if k not in ("talismans", "at")} | {"what": "talisman", "n": st["at"]})
        return out, builder.plan_paths(plan)

    # ---- set builder -------------------------------------------------------------------------------
    @staticmethod
    def _sig(f):
        return (tuple((p["id"], p["kind"], p.get("type"), p.get("n")) if p else None for p in f.pieces),
                (tuple(map(tuple, f.talisman["skills"])), tuple(f.talisman["slots"]), f.talisman.get("n"))
                if f.talisman else None)

    def build_search(self, p: dict):
        """Set builder: the sets that reach the wanted skills, closest first: with your armor and game
        armor (no rolls), then with the pieces your saved sets will get, then with new rolls (fewest
        first; equal rolls: the best defense or score)."""
        with self._lock:
            if not self.data:
                return {"error": "Game data not loaded."}
            if not p.get("skills"):
                return {"error": "Add at least one skill."}
            self._search_begin("Simulating augments")
            limit = max(1, min(MAX_RESULTS, int(p.get("limit") or 20)))
            o = self._options(p, value="score" if p.get("sortBy") == "score" else "defense", cost_first=True,
                              limit=limit + 5, seconds=max(1.0, float(p.get("seconds") or 30)))
            self._weapon = o.weapon
            gens = self.generators if (o.qurious_rolls or o.talisman_rolls) else None
            armors, talismans = self.box
            t0 = time.time()
            planned = []
            try:
                if p.get("planned", True) and self.saved_sets() and self.generators:
                    self._search_phase("Reading the saved sets' plan")
                    planned, o.plan = self._planned_pieces()
                    o.planned = planned
                extra, c2 = [], {"complete": True}
                if planned and not self._stopped():
                    # the same search with the saved sets' pieces and no new rolls (fast, so first: a stop
                    # later keeps them); listed after the sets that need nothing, before the ones with new rolls
                    self._search_phase("Searching with the saved sets' pieces", rollsTotal=0)
                    po = builder.Options(**{**o.__dict__, "qurious_rolls": 0, "talisman_rolls": 0,
                                            "max_cost": 0, "seconds": max(1.0, o.seconds / 3)})
                    extra, c2 = self._builder().search(po, armors, talismans, None, self.owned_decos)
                    extra = [f for f in extra if any(x and x["kind"] == "planned" for x in [*f.pieces, f.talisman])]
                    for f in extra:
                        f.tier = "planned"
                self._search_phase("Simulating augments", rollsTotal=o.qurious_rolls if gens else 0)
                found, counts = self._builder().search(o, armors, talismans, gens, self.owned_decos,
                                                       on_search=lambda: self._search_phase("Searching"))
                counts["complete"] = counts["complete"] and c2["complete"]
            except Exception as e:
                return {"error": f"Search failed: {e}"}
            finally:
                stopped = self._stopped()
                self._progress = None
            # yours / game armor -> the saved sets' pieces -> new rolls (fewest first)
            uses_planned = lambda f: any(x and x["kind"] == "planned" for x in [*f.pieces, f.talisman])
            free = [f for f in found if not builder.has_rolls(f) and not uses_planned(f)]
            for f in free:
                f.tier = "owned"
            extra += [f for f in found if not builder.has_rolls(f) and uses_planned(f)]
            for f in extra:
                f.tier = "planned"
            rolled = [f for f in found if builder.has_rolls(f)]
            for f in rolled:
                f.tier = "rolls"
            ordered = free + extra + rolled
            rows, seen = [], set()
            for f in ordered:
                sig = self._sig(f)
                if sig not in seen:
                    seen.add(sig)
                    rows.append(self._set_row(f, o.reqs))
            return {"sets": rows[:limit + len(extra)], "complete": counts["complete"] and not stopped,
                    "stopped": stopped, "planned": len(planned),
                    "candidates": sum(counts["armor"]) + counts["talismans"], "seconds": round(time.time() - t0, 2)}

    # ---- build optimizer ---------------------------------------------------------------------------
    def _loadout_items(self, key: int):
        L = self.loadout_list[int(key)]
        armors, talismans = self.box
        by_idx = {it.index: it for it in armors}
        tal = next((t for t in talismans if t.index == L.talisman), None)
        return L, [by_idx.get(i) for i in L.armor], tal

    def _weapon_slots(self, L) -> list[int]:
        w = next((w for w in self.box_weapons if w.index == L.weapon), None)
        info = self.data["weapons"].get(str(w.weapon_id)) if w else None
        return list(info["slots"]) if info else [0, 0, 0]

    def loadout_summaries(self):
        """Every loadout of the save, for the list: name, weapon and the name of each armor piece."""
        with self._lock:
            out = []
            for key, L in enumerate(self.loadout_list or []):
                _, armor, tal = self._loadout_items(key)
                w = next((w for w in self.box_weapons if w.index == L.weapon), None)
                winfo = self.data["weapons"].get(str(w.weapon_id)) if w else None
                out.append({"key": key, "name": L.name, "weaponName": self._name(winfo["names"]) if winfo else "",
                            "pieces": [self._armor_name(str(it.armor_id)) if it else None for it in armor],
                            "talisman": tal is not None})
            return out

    def optimizer_load(self, key: int, preset=None):
        """A loadout as it is in the save: pieces, decorations, skills and score."""
        with self._lock:
            if not self.loadout_list:
                return {"error": "No equipment found in the save."}
            L, armor, tal = self._loadout_items(key)
            weapon = self._weapon_slots(L)
            w = next((w for w in self.box_weapons if w.index == L.weapon), None)
            current = self._current_row(L, armor, tal, weapon, preset)
            winfo = self.data["weapons"].get(str(w.weapon_id)) if w else None
            current["weaponName"] = self._name(winfo["names"]) if winfo else ""
            return {"current": current, "weapon": weapon}

    def _current_row(self, L, armor, tal, weapon, preset) -> dict:
        b = self._builder()
        pieces = []
        for it in armor:
            pieces.append(b._item_info(it) if it else None)
        tinfo = {"kind": "owned", "box": tal.index, "skills": list(tal.skills), "slots": list(tal.slots)} if tal else None
        totals = {}
        for info in pieces:
            for s, l in (info["skills"] if info else []):
                totals[s] = totals.get(s, 0) + l
        for s, l in (tinfo["skills"] if tinfo else []):
            totals[s] = totals.get(s, 0) + l
        decos = []
        owners = [L.weapon] + list(L.armor) + [L.talisman]
        own_slots = [weapon] + [info["slots"] if info else [0, 0, 0] for info in pieces] + [tinfo["slots"] if tinfo else [0, 0, 0]]
        free = []
        for o, (idx, sl) in enumerate(zip(owners, own_slots)):
            ids = L.decos.get(idx, []) if idx is not None else []
            levels = [lv for lv in sl if lv]
            for k, lv in enumerate(levels):
                did = ids[k] if k < len(ids) else 0
                d = b.decos.get(did) if did else None
                if d:
                    decos.append((o, k, did, False))
                    totals[d["skill"]] = totals.get(d["skill"], 0) + d["points"]
                else:
                    free.append(lv)
        skills = sorted(((s, min(l, b.max_levels.get(s, 7))) for s, l in totals.items() if l > 0),
                        key=lambda e: (-e[1], e[0]))
        weights, slot_values = self._preset_values(preset)
        score = sum(weights.get(s, 0) * l for s, l in skills) + sum(slot_values[lv] for lv in free)
        defense = sum(info["defense"] for info in pieces if info)
        found = builder.Found.of(pieces, tinfo, decos, skills, sorted(free, reverse=True), 0, defense, round(score, 2))
        self._weapon = weapon
        row = self._set_row(found)
        row["name"] = L.name
        return row

    def optimize(self, p: dict):
        """Build optimizer: the best set without rolls, then better sets with more rolls (each needs more
        rolls and is worth more), keeping the wanted skills."""
        with self._lock:
            if not self.loadout_list:
                return {"error": "No equipment found in the save."}
            L, armor, tal = self._loadout_items(p.get("loadout") or 0)
            o = self._options({**p, "ownedArmor": True, "ownedTalismans": True,
                               "quriousOwnedOnly": not p.get("gameArmor", False)},
                              value="score", cost_first=False, limit=6, seconds=float(p.get("seconds") or 12))
            o.game_armor = bool(p.get("gameArmor", False))
            o.owned_decos = bool(p.get("ownedDecos", True))
            self._search_begin("Reading the saved sets' plan")
            if p.get("planned", True) and self.saved_sets():
                o.planned, o.plan = self._planned_pieces()
            self._search_phase("Searching")
            weapon = o.weapon
            current = self._current_row(L, armor, tal, weapon, p.get("preset"))
            self._weapon = weapon
            armors, talismans = self.box
            t0 = time.time()
            try:
                front, counts = self._builder().best_and_improve(
                    o, (armor, tal), armors, talismans, self.generators, self.owned_decos)
            except Exception as e:
                return {"error": f"Optimization failed: {e}"}
            finally:
                self._progress = None
            rows = [self._set_row(f, o.reqs, current["score"]) for f in front]
            # changed parts against the loadout
            cur_keys = [(pc["id"], pc["kind"] == "roll") if pc else None for pc in current["pieces"]]
            for r in rows:
                r["changed"] = [i for i, pc in enumerate(r["pieces"])
                                if (pc["id"] if pc else None) != (cur_keys[i][0] if cur_keys[i] else None)
                                or (pc and pc["kind"] in ("roll", "planned"))]
                ct, rt = current["talisman"], r["talisman"]
                if (ct and [(s["id"], s["level"]) for s in ct["skills"]]) != (rt and [(s["id"], s["level"]) for s in rt["skills"]]) \
                        or (rt and rt["kind"] in ("roll", "planned")):
                    r["changed"].append(5)
            return {"current": current, "sets": rows, "complete": counts["complete"], "proven": counts.get("proven", True),
                    "seconds": round(time.time() - t0, 2)}

    # ---- saved sets and planner -------------------------------------------------------------------
    def saved_sets(self):
        return self.settings.get("savedSets") or []

    def check_saved_sets(self, force: bool = False):
        """Check every saved set against the save as it is now (see ``Planner.check``) and keep the
        result with the set; sets already checked against this save are not checked again."""
        with self._lock:
            if not self.generators:
                return {"error": "Select a hunter first."}
            self._search_begin("Checking the saved sets")
            try:
                return {"sets": self._check_sets(force)}
            finally:
                self._progress = None

    def _check_sets(self, force: bool = False) -> list[dict]:
        if not self.generators:
            return self.saved_sets()
        state = str(hash(tuple(tuple(g.state()) for g in self.generators)))
        sets = [dict(x) for x in self.saved_sets()]
        pl = planner.Planner(self.data, self.melding)
        changed = False
        try:
            for x in sets:
                if not force and (x.get("check") or {}).get("state") == state:
                    continue
                try:
                    x["check"] = {**pl.check(x, self.generators, self.box[0], box_talismans=self.box[1]), "state": state,
                                  "when": time.strftime("%Y-%m-%d %H:%M")}
                except planner.Stopped:
                    raise
                except Exception as e:
                    x["check"] = {"error": str(e), "state": state}
                changed = True
            # a set saved with pieces inside or after the saved sets' roadmap (augments spent on another
            # set's piece before them) needs that roadmap: when the set alone needs more, count along it
            if any("together" not in (x.get("check") or {"together": 1}) and "error" not in x["check"] for x in sets):
                plan = self._saved_plan()
                for x in sets:
                    c = x.get("check") or {}
                    if not plan or "together" in c or "error" in c:
                        continue
                    t = pl.check(x, self.generators, self.box[0], together=plan)
                    worse = (c["missing"], c["augments"] + c["talismans"]) > (t["missing"], t["augments"] + t["talismans"])
                    if worse:
                        x["check"] = {**c, **t, "aloneAugments": c["augments"], "missingAlone": c["missing"]}
                    else:
                        c["together"] = False
        except planner.Stopped:
            pass
        if changed:
            self.save_settings({"savedSets": sets})
        return sets

    def save_set(self, row: dict, name: str, query: dict | None = None):
        """Keep a Set builder result (with the rolls it needs) for the planner."""
        sets = list(self.saved_sets())
        sid = max((x["id"] for x in sets), default=0) + 1
        sets.append({"id": sid, "name": (name or "").strip() or f"Set {sid}", "created": time.strftime("%Y-%m-%d %H:%M"),
                     "query": query or {}, "set": row, "targets": planner.targets_of(row)})
        self.save_settings({"savedSets": sets})
        return {"sets": sets, "id": sid}

    def delete_set(self, sid: int):
        sets = [x for x in self.saved_sets() if x["id"] != sid]
        self.save_settings({"savedSets": sets})
        return {"sets": sets}

    def rename_set(self, sid: int, name: str):
        sets = [dict(x, name=name.strip() or x["name"]) if x["id"] == sid else x for x in self.saved_sets()]
        self.save_settings({"savedSets": sets})
        return {"sets": sets}

    def make_plan(self, ids: list):
        """Roadmap of the rolls the chosen saved sets need, from the save as it is now, and its cost."""
        with self._lock:
            if not self.generators:
                return {"error": "Select a hunter first."}
            sets = [x for x in self.saved_sets() if x["id"] in set(ids)]
            if not sets:
                return {"error": "Choose at least one saved set."}
            t0 = time.time()
            self._search_begin("Planning")
            try:
                plan = planner.Planner(self.data, self.melding).plan(sets, self.generators, self.box[0], self.box[1])
            except planner.Stopped:
                return {"error": "Stopped."}
            except Exception as e:
                return {"error": f"Planning failed: {e}"}
            finally:
                self._progress = None
            return self._plan_view(plan, time.time() - t0)

    def _outcome_view(self, e) -> dict:
        d, sl, res, sk = e
        return {"def": d, "slots": sl, "res": list(res), "skills": [dict(self._skill(int(a)), delta=int(b)) for a, b in sk]}

    def _plan_view(self, plan: dict, seconds: float) -> dict:
        for seq in plan["armor"]:
            for st in seq["steps"]:
                st["result"] = self._outcome_view(st["expected"])
                st["rarity"] = self.data["all_armors"][st["id"]]["rare"] + 1
                st["burnName"] = self._armor_name(st["burnOn"]) if st["burnOn"] else None
        for g in plan["talismans"]:
            g["gradeName"] = "CBAS"[g["grade"]] if g["grade"] is not None and 0 <= g["grade"] < 4 else None
            for st in g["steps"]:
                st["skillRows"] = [dict(self._skill(int(a)), level=int(b)) for a, b in st["skills"]]
                st["targetName"] = self._skill(st["target"])["name"] if st["target"] else None
                st["targetColor"] = self._skill(st["target"])["color"] if st["target"] else None
        for t in plan["missing"]["armor"]:
            t["result"] = self._outcome_view(t["expected"])
        for d in plan["done"]:
            t = d["target"]
            d["name"] = "Talisman" if d["talisman"] else t["name"]
        for c in plan["newCopies"]:
            c["name"] = c["name"] or self._armor_name(c["id"])
            c["rarity"] = self.data["all_armors"][c["id"]]["rare"] + 1
            c["part"] = self.data["all_armors"][c["id"]]["part"]
        for c in plan["craft"]:
            a = self.data["all_armors"].get(str(c["id"]))
            c["part"] = a["part"] if a else None
        for key in ("amber", "meld"):
            for m in plan["materials"][key]:
                m["name"] = self._name(m.pop("names"))
        plan["materials"]["mixNames"] = [m["name"] for m in plan["materials"]["amber"]]
        plan["seconds"] = round(seconds, 2)
        return plan

    # ---- export ------------------------------------------------------------------------------------
    def export_kinds(self):
        return [{"kind": k, "label": v[0], "formats": v[1]} for k, v in EXPORTS.items()]

    def _names(self) -> Names:
        tables = {"skills": self.data["skills"], "armors": self.data["armors"]}
        return Names(tables, "en")

    def export_text(self, kind: str, fmt: str):
        """The box (or part of it) as text: wiki-db import lines (like MHRiseExporter), CSV or JSON."""
        with self._lock:
            if self.save_file is None:
                return {"error": "Select a hunter first."}
            if kind not in EXPORTS or fmt not in EXPORTS[kind][1]:
                return {"error": "This export is not available in that format."}
            try:
                text, count = self._export(kind, fmt)
            except Exception as e:
                return {"error": f"Export failed: {e}"}
            ext = {"wikidb": "txt", "csv": "csv", "json": "json"}[fmt]
            name = FILE_NAMES.get((kind, fmt), f"MHRise_{kind}.{ext}")
            return {"text": text, "count": count, "fileName": name}

    def _export(self, kind: str, fmt: str):
        if fmt == "wikidb":
            names = self._names()
            if kind == "talismans":
                lines = talisman_lines(self.save_file, names)
            else:
                buildups = {f"{b['table']}:{b['id']}": {"values": b["values"], "cat": b["category"]} for b in self.data["base"]}
                lines = qurious_lines(self.save_file, {**names.t, "buildups": buildups}, names)
            return "\n".join(lines) + ("\n" if lines else ""), len(lines)
        data = {}
        if kind in ("talismans", "everything"):
            data["talismans"] = self._talisman_records()
        if kind in ("qurious", "armor", "everything"):
            data["armor"] = self._armor_records(only_qurious=kind == "qurious")
        if kind in ("decorations", "everything"):
            data["decorations"] = self._deco_records()
        if fmt == "json":
            return json.dumps(data if kind == "everything" else next(iter(data.values())), ensure_ascii=False, indent=2), \
                sum(len(v) for v in data.values())
        rows = next(iter(data.values()))
        flat = [_csv_row(kind, r) for r in rows]
        out = io.StringIO()
        if flat:
            w = csv.DictWriter(out, fieldnames=list(flat[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(flat)
        return out.getvalue(), len(rows)

    def _skill_list(self, pairs):
        return [{"name": self._skill(s)["name"], "level": l} for s, l in pairs]

    def _talisman_records(self):
        return [{"skills": self._skill_list(t.skills), "slots": list(t.slots)} for t in self.box[1]]

    def _armor_records(self, only_qurious: bool):
        out = []
        for it in self.box[0]:
            if only_qurious and not it.augmented:
                continue
            a = self.data["all_armors"][str(it.armor_id)]
            base = _expand_slots(a["slots"])
            slots = apply_slot_bonus(base, it.slot_points) if it.slot_points else sorted(base, reverse=True)
            levels = {sid: lv for sid, lv in a["skills"]}
            for sid, v in it.skills or []:
                levels[sid] = levels.get(sid, 0) + v
            out.append({"part": builder.PART_NAMES[a["part"]], "name": self._name(a["names"]), "rarity": a["rare"] + 1,
                        "qurious": it.augmented, "defense": a.get("defMax", 0) + it.defense, "defenseChange": it.defense,
                        "resistances": [x + y for x, y in zip(a.get("res", [0] * 5), it.resistances or [0] * 5)],
                        "slots": (list(slots) + [0, 0, 0])[:3],
                        "skills": self._skill_list([(s, l) for s, l in levels.items() if l > 0])})
        return out

    def _deco_records(self):
        b = self._builder()
        out = []
        for did, n in sorted(self.owned_decos.items(), key=lambda e: (-b.decos.get(e[0], {}).get("level", 0), e[0])):
            d = b.decos.get(did)
            if d:
                out.append({"name": self._name(d["names"]), "skill": self._skill(d["skill"])["name"],
                            "points": d["points"], "slotLevel": d["level"], "owned": n})
        return out

    def save_text(self, file_name: str, text: str):
        """Save dialog, then write the text (UTF-8)."""
        import webview
        result = webview.windows[0].create_file_dialog(webview.SAVE_DIALOG, save_filename=file_name)
        if not result:
            return {"saved": None}
        path = Path(result if isinstance(result, str) else result[0])
        path.write_text(text, encoding="utf-8")
        return {"saved": str(path)}
