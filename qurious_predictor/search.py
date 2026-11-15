"""Filter matching and the parallel roll search.

A search is a set of *streams*: (armor piece, augment option). Each stream replays that option's
generator from the save state for that piece, roll after roll, and reports the rolls that pass the
filters (or, when ranking, its best-scoring roll). Streams advance in small chunks, so every stream
moves forward at about the same pace and the closest matches show up first.

Two implementations with the same interface (``snapshot(since)``, ``cancel()``, ``done``):

* ``NativeSearch``: the Rust engine (``_native``, built from native/) on a thread pool. Used whenever
  the extension is available.
* ``Search``: the pure Python reference, one worker process per CPU core. Fallback, and the
  reference the Rust port is tested against. ``QURIOUS_ENGINE=python`` forces it.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import queue
import threading
import time

from mhrise_exporter.export import _expand_slots, apply_slot_bonus

from . import engine

try:
    from . import _native
except ImportError:  # running from source without building the extension
    _native = None

CHUNK = 25            # rolls per stream before moving on to the next stream
REPORT_EVERY = 0.25   # seconds between progress messages


# ---- filters ---------------------------------------------------------------------------------------

def skill_groups(filters: dict) -> list[list[tuple[int, int]]]:
    """``filters["skills"]`` as AND-of-OR groups: [[(id, min level), ...], ...].

    Each group needs one of its skills at that level or higher on the piece after the augment; every
    group must hold. With ``filters["gainOnly"]`` the augment itself must also raise that skill.
    Older settings stored a flat list of {id, level}: each becomes its own group.
    """
    groups = []
    for g in filters.get("skills") or []:
        items = g if isinstance(g, list) else [g]
        goals = [(int(w["id"]), max(1, int(w.get("level") or 1))) for w in items]
        if goals:
            groups.append(goals)
    return groups


def active(filters: dict) -> bool:
    return bool(skill_groups(filters) or any(filters.get("slots") or []) or filters.get("minDef") is not None
                or filters.get("noSkillLoss") or filters.get("noNegRes"))


def adding_tables(tables: engine.Tables) -> set[int]:
    """Augment tables that can add skills (some, like the Pure armor's, never do)."""
    return {table for table, cats in tables.lots.items()
            if any(lot > 0 and tables.base[(table, bid)].cost > 0 for bid, lot in cats.get(engine.CAT_SKILL, []))}


def reachable(armor: dict, filters: dict, tables: engine.Tables, add_tables: set[int]) -> list[int]:
    """Augment options that can ever pass the skill filters on this piece (others are skipped)."""
    max_levels = tables.max_levels
    addable = {s for s, _ in tables.skill_costs} if armor["table"] in add_tables else set()
    base = {s: lv for s, lv in armor["skills"]}
    groups = skill_groups(filters)
    room = len(base) < engine.MAX_SKILLS_PER_PIECE  # a piece with 5 skills never gets a new one
    gain = bool(filters.get("gainOnly"))

    def possible(sid: int, level: int) -> bool:
        top = max_levels.get(sid, 99) + 1
        if level > top:
            return False
        if level <= base.get(sid, 0) and not gain:
            return True
        return sid in addable and (room or sid in base) and base.get(sid, 0) < top

    if not all(any(possible(sid, level) for sid, level in g) for g in groups):
        return []  # some group can never be met on this piece
    # Stability never adds skills: it only works when every group is already met by the piece.
    needs_add = any(gain or all(level > base.get(sid, 0) for sid, level in g) for g in groups)
    return [t for t in engine.TYPE_NAMES if not (t == engine.TYPE_STABILITY and needs_add)]


def matcher(armor: dict, filters: dict):
    base_lv = {s: lv for s, lv in armor["skills"]}
    groups = skill_groups(filters)
    min_slots = sorted((int(x) for x in (filters.get("slots") or [0, 0, 0])), reverse=True)
    base_slots = _expand_slots(armor["slots"])
    min_def = filters.get("minDef")
    no_loss, no_neg = filters.get("noSkillLoss"), filters.get("noNegRes")
    gain = bool(filters.get("gainOnly"))  # the augment itself must raise the skill

    def ok(s: engine.Summary) -> bool:
        delta = {}
        for sid, v in s.skills:
            delta[sid] = delta.get(sid, 0) + v
        for g in groups:
            if not any(base_lv.get(sid, 0) + delta.get(sid, 0) >= level and (not gain or delta.get(sid, 0) > 0)
                       for sid, level in g):
                return False
        if no_loss and any(v < 0 for v in delta.values()):
            return False
        if no_neg and any(v < 0 for v in s.resistances.values()):
            return False
        if min_def is not None and s.defense < int(min_def):
            return False
        if any(min_slots):
            final = (apply_slot_bonus(base_slots, s.slots) + [0, 0, 0])[:3]
            if any(have < need for have, need in zip(final, min_slots)):
                return False
        return True
    return ok


# ---- worker process --------------------------------------------------------------------------------

def _worker(wid, table_data, armors, states, streams, filters, max_matches, limit, out, stop, rank=None):
    """Filter mode: report rolls that pass ``filters``. Rank mode (``rank`` = {"preset"}): score every roll
    and report each stream's best one so far (the earliest on ties). Score and gain differ by a constant
    per stream, so the best roll is the same for both."""
    from . import gamedata
    from .ranking import Scorer
    from .rng import XorShift128

    tables = gamedata.tables(table_data)
    live = []
    for key, (aid, t) in streams:
        a = armors[aid]
        live.append({"key": key, "armor": a, "type": t, "rng": XorShift128(states[engine.seed_index(a["cost"], t)]),
                     "skills": [tuple(x) for x in a["skills"]], "n": 0, "found": 0,
                     "ok": None if rank else matcher(a, filters),
                     "scorer": Scorer(a, rank["preset"], tables.max_levels) if rank else None, "best": None})
    last = 0.0
    while live and not stop.is_set():
        for st in list(live):
            a, t, rng = st["armor"], st["type"], st["rng"]
            for _ in range(CHUNK):
                st["n"] += 1
                s = engine.summarize(engine.create_result(rng, tables, a["table"], a["cost"], st["skills"], t))
                if rank:
                    score, gain = st["scorer"].score(s)
                    if st["best"] is None or score > st["best"]:
                        st["best"] = score
                        out.put(("match", st["key"], st["n"], s, (score, gain)))
                elif st["ok"](s):
                    st["found"] += 1
                    out.put(("match", st["key"], st["n"], s))
                if st["found"] >= max_matches or st["n"] >= limit:
                    live.remove(st)
                    out.put(("end", st["key"], st["n"]))
                    break
        now = time.monotonic()
        if now - last > REPORT_EVERY:
            last = now
            out.put(("progress", wid, {st["key"]: st["n"] for st in live}))
    for st in live:  # stopped
        out.put(("end", st["key"], st["n"]))
    out.put(("done", wid, None))


class Search:
    """Runs streams over worker processes; results are read with ``snapshot(since)`` (thread-safe)."""

    def __init__(self, data: dict, generators, streams: list[tuple[str, int]], filters: dict,
                 max_matches: int, limit: int, row, rank: dict | None = None):
        self.streams = streams
        self.row = row                # (armor id, Summary, n) -> dict for the page
        self.events = []              # {"key", "armor", "type", "n", "row"} in arrival order
        self.scanned = {k: 0 for k in range(len(streams))}
        self.ended = set()
        self.done = False
        self.cancelled = False
        self._lock = threading.Lock()
        ctx = mp.get_context("spawn")
        self._stop = ctx.Event()
        self._out = ctx.Queue()
        table_keys = ("base", "armor_lots", "category_lots", "skill_costs", "max_levels")
        table_data = {k: data[k] for k in table_keys}
        armors = {aid: data["armors"][aid] for aid, _ in streams}
        states = [g.state() for g in generators]
        n_workers = max(1, min(len(streams), (os.cpu_count() or 2) - 1, 15))
        keyed = list(enumerate(streams))
        self._procs = []
        for w in range(n_workers):
            part = keyed[w::n_workers]
            p = ctx.Process(target=_worker, daemon=True,
                            args=(w, table_data, {aid: armors[aid] for _, (aid, _t) in part}, states, part,
                                  filters, max_matches, limit, self._out, self._stop, rank))
            p.start()
            self._procs.append(p)
        threading.Thread(target=self._collect, daemon=True).start()

    def _collect(self):
        alive = len(self._procs)
        while alive:
            try:
                kind, a, b, *rest = self._out.get(timeout=0.5)
            except queue.Empty:
                if not any(p.is_alive() for p in self._procs):
                    break
                continue
            with self._lock:
                if kind == "match":
                    aid, t = self.streams[a]
                    self.scanned[a] = max(self.scanned[a], b)
                    ev = {"key": a, "armor": aid, "type": t, "n": b, "row": self.row(aid, rest[0], b)}
                    if len(rest) > 1:
                        ev["score"], ev["gain"] = rest[1]
                    self.events.append(ev)
                elif kind == "progress":
                    for k, n in b.items():
                        self.scanned[k] = max(self.scanned[k], n)
                elif kind == "end":
                    self.scanned[a] = max(self.scanned[a], b)
                    self.ended.add(a)
                elif kind == "done":
                    alive -= 1
        for p in self._procs:
            p.join(timeout=2)
        with self._lock:
            self.done = True

    def cancel(self):
        self.cancelled = True
        self._stop.set()

    def snapshot(self, since: int = 0) -> dict:
        with self._lock:
            running = [n for k, n in self.scanned.items() if k not in self.ended]
            return {
                "done": self.done,
                "cancelled": self.cancelled,
                "events": self.events[since:],
                "total": sum(self.scanned.values()),
                "depth": min(running) if running else max(self.scanned.values(), default=0),
                "streams": {k: {"scanned": n, "ended": k in self.ended} for k, n in self.scanned.items()},
            }


# ---- Rust engine -------------------------------------------------------------------------------------

def native_available() -> bool:
    return _native is not None and os.environ.get("QURIOUS_ENGINE", "").lower() != "python"


_TABLES_CACHE: dict = {}


def native_tables(data: dict):
    """The tables as a ``_native.Tables`` (built once per game data)."""
    key = (id(data), data.get("fingerprint"))
    if key not in _TABLES_CACHE:
        _TABLES_CACHE.clear()
        _TABLES_CACHE[key] = _native.Tables(
            [(b["table"], b["id"], b["category"], b["cost"], list(b["values"]), list(b["lots"])) for b in data["base"]],
            [tuple(x) for x in data["armor_lots"]],
            {int(k): list(v) for k, v in data["category_lots"].items()},
            [tuple(x) for x in data["skill_costs"]],
            {int(k): v for k, v in data["max_levels"].items()},
        )
    return _TABLES_CACHE[key]


def summary_of(t) -> engine.Summary:
    """``_native`` summary tuple -> engine.Summary."""
    defense, slots, res, skills = t
    return engine.Summary(defense=defense, slots=slots,
                          resistances={e: v for e, v in zip(engine.ELEMENTS, res) if v},
                          skills=[tuple(x) for x in skills])


def rolls(data: dict, generators, armor: dict, buildup_type: int, count: int) -> tuple[int, list[engine.Summary]]:
    """(generator index, the next ``count`` augments) for one piece and option."""
    seed = engine.seed_index(armor["cost"], buildup_type)
    if native_available():
        out = _native.rolls(native_tables(data), generators[seed].state(), armor["table"], armor["cost"],
                            [tuple(x) for x in armor["skills"]], buildup_type, count)
        return seed, [summary_of(t) for t in out]
    from .predict import next_rolls
    from . import gamedata
    seed, rs = next_rolls(generators, gamedata.tables(data), armor, buildup_type, count)
    return seed, [r.summary for r in rs]


class NativeSearch:
    """``Search`` on the Rust engine: same constructor and snapshot format."""

    def __init__(self, data: dict, generators, streams: list[tuple[str, int]], filters: dict,
                 max_matches: int, limit: int, row, rank: dict | None = None):
        self.streams = streams
        self.row = row
        self.events = []
        self.cancelled = False
        self._lock = threading.Lock()
        args = []
        for aid, t in streams:
            a = data["armors"][aid]
            args.append((a["table"], a["cost"], [tuple(x) for x in a["skills"]], list(a["slots"]), t,
                         generators[engine.seed_index(a["cost"], t)].state()))
        flt = preset = None
        if rank:
            p = rank["preset"]
            preset = ([(int(k), float(v)) for k, v in p.get("weights", {}).items()],
                      [float(x) for x in (list(p.get("slots", [])) + [0, 0, 0, 0])[:4]], float(p.get("defense") or 0))
        else:
            min_def = filters.get("minDef")
            flt = (skill_groups(filters), [int(x) for x in (list(filters.get("slots") or []) + [0, 0, 0])[:3]],
                   None if min_def is None else int(min_def), bool(filters.get("noSkillLoss")),
                   bool(filters.get("noNegRes")), bool(filters.get("gainOnly")))
        self._scan = _native.Scan(native_tables(data), args, flt, preset, int(max_matches), int(limit), 0)

    @property
    def done(self) -> bool:
        return self._scan.done

    def cancel(self):
        self.cancelled = True
        self._scan.cancel()

    def snapshot(self, since: int = 0) -> dict:
        with self._lock:
            new, scanned, ended, done = self._scan.poll(len(self.events))
            for k, n, defense, slots, res, skills, score in new:
                aid, t = self.streams[k]
                ev = {"key": k, "armor": aid, "type": t, "n": n,
                      "row": self.row(aid, summary_of((defense, slots, res, skills)), n)}
                if score is not None:
                    ev["score"], ev["gain"] = round(score[0], 3), round(score[1], 3)
                self.events.append(ev)
            running = [n for k, n in enumerate(scanned) if not ended[k]]
            return {
                "done": done,
                "cancelled": self.cancelled,
                "events": self.events[since:],
                "total": sum(scanned),
                "depth": min(running) if running else max(scanned, default=0),
                "streams": {k: {"scanned": n, "ended": ended[k]} for k, n in enumerate(scanned)},
            }


def start(*args, **kwargs):
    """A search on the Rust engine when available, else on Python worker processes."""
    return (NativeSearch if native_available() else Search)(*args, **kwargs)
