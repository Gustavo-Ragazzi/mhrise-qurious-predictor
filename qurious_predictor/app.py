"""Desktop window (pywebview): Python API used by web/index.html."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from mhrise_exporter import core, steam
from mhrise_exporter.export import _expand_slots, apply_slot_bonus

from . import engine, gamedata, icons, savedata
from .predict import next_rolls

TITLE = "MH Rise Qurious Predictor"
WEB = Path(__file__).with_name("web") / "index.html"
EMPTY_FILTERS = {"skills": [], "slots": [0, 0, 0], "minDef": None, "noSkillLoss": False, "noNegRes": False}
DEFAULT_SETTINGS = {"rolls": 200, "lang": "en", "hunter": None, "armor": None, "type": engine.TYPE_AUGMENT,
                    "filters": EMPTY_FILTERS, "game_dir": None}


def filters_active(f: dict) -> bool:
    return bool(f.get("skills") or any(f.get("slots") or []) or f.get("minDef") is not None
                or f.get("noSkillLoss") or f.get("noNegRes"))


class Api:
    def __init__(self):
        self._lock = threading.Lock()
        self.cache_dir = gamedata.default_cache_dir()
        self.settings_file = self.cache_dir / "settings.json"
        self.settings = dict(DEFAULT_SETTINGS)
        try:
            self.settings.update(json.loads(self.settings_file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        self.data = None
        self.tables = None
        self.generators = None
        self.owned = {}
        self.hunters = []

    # ---- setup ------------------------------------------------------------------------------------

    def init(self):
        """Game data, icons, hunters and settings. Slow only on the very first run."""
        with self._lock:
            game_dir = Path(self.settings["game_dir"]) if self.settings.get("game_dir") else steam.find_game_dir()
            if not game_dir or not (Path(game_dir) / "re_chunk_000.pak").exists():
                return {"error": "Monster Hunter Rise was not found. Choose the game folder."}
            self.data = gamedata.load(Path(game_dir), self.cache_dir, log=lambda m: None)
            self.tables = gamedata.tables(self.data)
            icon_map = icons.load(Path(game_dir), self.cache_dir, self.data.get("fingerprint", ""))
            self.hunters = []
            for acc in steam.find_accounts():
                try:
                    hunters, _ = core.read_hunters(acc.save_dir, acc.steamid64)
                except Exception:
                    continue
                self.hunters += [(acc, h) for h in hunters if h.used]
            langs = sorted({l for n in self.data["skills"].values() for l in n})
            return {
                "settings": self.settings,
                "icons": icon_map,
                "langs": langs,
                "hunters": [{"key": f"{acc.steamid64}:{h.slot}", "name": h.name, "hr": h.hr, "mr": h.mr,
                             "slot": h.slot, "persona": acc.persona} for acc, h in self.hunters],
                "types": [{"id": t, "name": n} for t, n in engine.TYPE_NAMES.items()],
            }

    def choose_game_dir(self):
        import webview
        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if result:
            self.save_settings({"game_dir": result[0]})
            return True
        return False

    def save_settings(self, values: dict):
        self.settings.update({k: v for k, v in values.items() if k in DEFAULT_SETTINGS})
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.settings_file.write_text(json.dumps(self.settings), encoding="utf-8")
        except OSError:
            pass
        return True

    # ---- data -------------------------------------------------------------------------------------

    def _name(self, names: dict) -> str:
        lang = self.settings.get("lang", "en")
        return names.get(lang) or names.get("en") or next(iter(names.values()), "?")

    def _skill(self, sid: int) -> dict:
        return {"id": sid, "name": self._name(self.data["skills"].get(str(sid), {"en": f"#{sid}"})),
                "color": self.data["skill_colors"].get(str(sid), 0),
                "max": self.data["max_levels"].get(str(sid), 0) + 1}  # _MaxLevel is 0-based

    def skills(self):
        """Every skill that qurious crafting can add, for the skill filter."""
        ids = sorted({s for s, _ in self.tables.skill_costs})
        return sorted((self._skill(s) for s in ids), key=lambda s: s["name"].lower())

    def load_hunter(self, key: str):
        with self._lock:
            match = [(a, h) for a, h in self.hunters if f"{a.steamid64}:{h.slot}" == key]
            if not match:
                return {"error": "Hunter not found."}
            acc, h = match[0]
            try:
                save = core.load_slot(acc.save_dir, acc.steamid64, h.slot)
                self.generators = savedata.manual_generators(save)
                owned = savedata.owned_armor(save)
            except Exception as e:
                return {"error": f"Cannot read the save: {e}"}
            self.save_settings({"hunter": key})
            self.owned = {str(o.armor_id): o for o in owned if str(o.armor_id) in self.data["armors"]}
            armors = []
            for aid, o in self.owned.items():
                a = self.data["armors"][aid]
                armors.append({
                    "id": aid, "name": self._name(a["names"]), "part": a["part"], "rare": a["rare"],
                    "cost": a["cost"], "count": o.count, "augmented": o.augmented,
                    "slots": (_expand_slots(a["slots"]) + [0, 0, 0])[:3],
                    "skills": [dict(self._skill(s), level=lv) for s, lv in a["skills"]],
                })
            armors.sort(key=lambda x: (x["part"], x["cost"], x["name"]))
            return {"armors": armors}

    def predict(self, armor_id: str, count: int):
        """Next ``count`` rolls of every augment type for one armor piece."""
        with self._lock:
            a = self.data["armors"].get(str(armor_id))
            if not a or not self.generators:
                return {"error": "Select a hunter and an armor piece."}
            count = max(1, min(1000, int(count)))
            self.save_settings({"armor": str(armor_id), "rolls": count})
            out = {}
            for t in engine.TYPE_NAMES:
                seed, rolls = next_rolls(self.generators, self.tables, a, t, count)
                out[t] = {"seed": seed, "rolls": [self._row(a, r.n, r.summary) for r in rolls]}
            return {"types": out, "sameCost": self._same_cost(a)}

    # ---- search (background thread, polled by the page) ---------------------------------------------

    def find_start(self, armor_id: str, filters: dict, max_matches: int = 50, limit: int = 2_000_000):
        """Scan every augment option until ``max_matches`` rolls pass ``filters``.

        filters = {"skills": [{"id", "level"}]  (level = minimum level on the piece after the augment),
                   "slots": [lv, lv, lv]          (minimum final slot levels, 0 = any),
                   "minDef": int | None, "noSkillLoss": bool, "noNegRes": bool}
        """
        self.find_cancel()
        a = self.data["armors"].get(str(armor_id)) if self.data else None
        if not a or not self.generators:
            return {"error": "Select a hunter and an armor piece."}
        base_lv = {s: lv for s, lv in a["skills"]}
        problems = []
        for w in filters.get("skills", []):
            sid, level = int(w["id"]), max(1, int(w.get("level") or 1))
            name, have = self._skill(sid)["name"], base_lv.get(sid, 0)
            if level > have + 1:
                problems.append(f"{name} Lv{level} is impossible on this piece: it has Lv{have} and an augment "
                                "adds at most +1 to a skill.")
            elif have >= self.tables.max_levels.get(sid, 99) + 1 and level > have:
                problems.append(f"{name} is already at its max level on this piece.")
        if problems:
            return {"error": " ".join(problems)}
        job = {"armor": str(armor_id), "progress": {}, "types": {}, "done": False, "cancel": False}
        self._job = job

        def run():
            try:
                job["types"] = self._find(a, filters, max_matches, limit, job)
            finally:
                job["done"] = True
        threading.Thread(target=run, daemon=True).start()
        return {"started": True}

    def find_status(self):
        job = getattr(self, "_job", None)
        if not job:
            return {"done": True, "types": {}}
        return {"done": job["done"], "progress": dict(job["progress"]), "types": job["types"] if job["done"] else {},
                "sameCost": self._same_cost(self.data["armors"][job["armor"]])}

    def find_cancel(self):
        job = getattr(self, "_job", None)
        if job and not job["done"]:
            job["cancel"] = True
        return True

    def _matcher(self, a: dict, f: dict):
        base_lv = {s: lv for s, lv in a["skills"]}
        goals = [(int(w["id"]), max(1, int(w.get("level") or 1))) for w in f.get("skills", [])]
        min_slots = sorted((int(x) for x in (f.get("slots") or [0, 0, 0])), reverse=True)
        base_slots = _expand_slots(a["slots"])
        min_def = f.get("minDef")
        no_loss, no_neg = f.get("noSkillLoss"), f.get("noNegRes")

        def ok(s) -> bool:
            delta = {}
            for sid, v in s.skills:
                delta[sid] = delta.get(sid, 0) + v
            for sid, level in goals:
                if base_lv.get(sid, 0) + delta.get(sid, 0) < level:
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

    def _find(self, a: dict, f: dict, max_matches: int, limit: int, job: dict) -> dict:
        matches = self._matcher(a, f)
        base = {s: lv for s, lv in a["skills"]}
        need_skill = any(int(w.get("level") or 1) > base.get(int(w["id"]), 0) for w in f.get("skills", []))
        skills = [tuple(x) for x in a["skills"]]
        state = {}
        for t in engine.TYPE_NAMES:
            seed = engine.seed_index(a["cost"], t)
            state[t] = {"seed": seed, "rng": self.generators[seed].copy(), "rolls": [], "scanned": 0,
                        "impossible": t == engine.TYPE_STABILITY and need_skill}  # Stability adds no skills
        active = [t for t in state if not state[t]["impossible"]]
        while active and not job["cancel"]:
            for t in list(active):  # round-robin so every tab advances together
                st = state[t]
                for _ in range(1000):
                    st["scanned"] += 1
                    s = engine.summarize(engine.create_result(st["rng"], self.tables, a["table"], a["cost"],
                                                              skills, t))
                    if matches(s):
                        st["rolls"].append(self._row(a, st["scanned"], s))
                    if len(st["rolls"]) >= max_matches or st["scanned"] >= limit:
                        active.remove(t)
                        break
                job["progress"][t] = {"scanned": st["scanned"], "found": len(st["rolls"])}
        return {t: {"seed": st["seed"], "rolls": st["rolls"], "scanned": st["scanned"],
                    "impossible": st["impossible"], "cancelled": job["cancel"]} for t, st in state.items()}

    def _same_cost(self, a: dict) -> int:
        return sum(1 for aid in self.owned if self.data["armors"][aid]["cost"] == a["cost"])

    def _row(self, a: dict, n: int, s) -> dict:
        base = _expand_slots(a["slots"])
        new = (apply_slot_bonus(base, s.slots) + [0, 0, 0])[:3]
        old = (sorted(base, reverse=True) + [0, 0, 0])[:3]
        return {
            "n": n,
            "def": s.defense,
            "slotPoints": s.slots,
            "slots": [{"lv": lv, "up": lv > ob} for lv, ob in zip(new, old)],
            "res": [s.resistances.get(e, 0) for e in engine.ELEMENTS],
            "skills": [dict(self._skill(k), v=v) for k, v in s.skills],
        }


def main():
    import webview

    api = Api()
    webview.create_window(TITLE, WEB.as_uri(), js_api=api, width=1360, height=860, min_size=(1000, 600),
                          background_color="#14110d")
    webview.start()


if __name__ == "__main__":
    main()
