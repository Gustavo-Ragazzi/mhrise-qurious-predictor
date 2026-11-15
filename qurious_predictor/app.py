"""Desktop window (pywebview): Python API used by web/index.html."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from mhrise_exporter import core, steam
from mhrise_exporter.export import _expand_slots, apply_slot_bonus

from . import engine, gamedata, icons, ranking, savedata, search

TITLE = "MH Rise Qurious Predictor"
WEB = Path(__file__).with_name("web") / "index.html"
EMPTY_FILTERS = {"skills": [], "slots": [0, 0, 0], "minDef": None, "noSkillLoss": False, "noNegRes": False}
LIST_DEFAULTS = {"ownedOnly": False, "rarity": 0, "part": -1}
DEFAULT_SETTINGS = {"rolls": 200, "lang": "en", "hunter": None, "armor": None, "type": engine.TYPE_AUGMENT,
                    "filters": EMPTY_FILTERS, "game_dir": None, "list": LIST_DEFAULTS,
                    "mode": "piece", "presets": [], "preset": "builtin:meta", "rankBy": "score",
                    "rankDepth": 200}


def _merge_skills(pairs):
    """Same skill lotted more than once in one augment -> one entry with the total (e.g. +2)."""
    total = {}
    for sid, v in pairs:
        total[sid] = total.get(sid, 0) + v
    return [(sid, v) for sid, v in total.items() if v]


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
            return {"armors": self._armor_list()}

    def _armor_list(self) -> list[dict]:
        """Every qurious-capable piece in the game (G rank). Pieces that exist twice with the same
        name, stats and augment table (variants) are listed once, preferring the owned one."""
        picked = {}
        for aid, a in self.data["armors"].items():
            key = (a["names"].get("en"), a["part"], a["cost"], a["table"], str(a["skills"]), str(a["slots"]))
            cur = picked.get(key)
            if cur is None or (aid in self.owned and cur not in self.owned):
                picked[key] = aid
        armors = []
        for aid in picked.values():
            a, o = self.data["armors"][aid], self.owned.get(aid)
            armors.append({
                "id": aid, "name": self._name(a["names"]), "part": a["part"], "rarity": a["rare"] + 1,
                "series": int(aid) & 0xFFFF, "cost": a["cost"], "count": o.count if o else 0,
                "augmented": o.augmented if o else 0,
                "slots": (_expand_slots(a["slots"]) + [0, 0, 0])[:3],
                "skills": [dict(self._skill(s), level=lv) for s, lv in a["skills"]],
            })
        armors.sort(key=lambda x: (-x["rarity"], x["series"], x["part"]))
        return armors

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
                seed, rolls = search.rolls(self.data, self.generators, a, t, count)
                out[t] = {"seed": seed, "rolls": [self._row(a, n, s) for n, s in enumerate(rolls, 1)]}
            return {"types": out, "sameCost": self._same_cost(a)}

    # ---- search (worker processes, polled by the page) -----------------------------------------------

    def _skill_problems(self, armors: list[dict], filters: dict) -> list[str]:
        """Filters no piece can ever meet (level above the skill's max, or a skill qurious cannot add)."""
        problems = []
        addable = {s for s, _ in self.tables.skill_costs}
        for g in search.skill_groups(filters):
            for sid, level in g:
                name, max_lv = self._skill(sid)["name"], self.tables.max_levels.get(sid, 99) + 1
                if level > max_lv:
                    problems.append(f"{name} only goes up to Lv{max_lv}.")
                elif sid not in addable and not any(lv >= level for a in armors for s, lv in a["skills"] if s == sid):
                    problems.append(f"Qurious crafting cannot add {name}.")
        return problems

    def _start(self, armor_ids: list[str], filters: dict, max_matches: int, limit: int):
        self.find_cancel()
        if not self.data or not self.generators:
            return {"error": "Select a hunter first."}
        armors = [self.data["armors"][aid] for aid in armor_ids if aid in self.data["armors"]]
        if not armors:
            return {"error": "No armor piece to search."}
        if not search.active(filters):
            return {"error": "Add at least one filter to search."}
        problems = self._skill_problems(armors, filters)
        if problems:
            return {"error": " ".join(problems)}
        add_tables = search.adding_tables(self.tables)
        streams = [(aid, t) for aid in armor_ids if aid in self.data["armors"]
                   for t in search.reachable(self.data["armors"][aid], filters, self.tables, add_tables)]
        if not streams:
            if len(armors) == 1:
                never_adds = armors[0]["table"] not in add_tables
                return {"error": "Qurious crafting never adds skills to this piece." if never_adds
                        else "No augment option can ever pass these skill filters on this piece."}
            return {"error": "No listed armor piece can ever pass these filters."}
        self._job = search.start(self.data, self.generators, streams, filters, max_matches, limit,
                                  lambda aid, s, n: self._row(self.data["armors"][aid], n, s))
        return {"started": True, "streams": [{"armor": aid, "type": t} for aid, t in streams]}

    def find_start(self, armor_id: str, filters: dict, max_matches: int = 50, limit: int = 5_000_000):
        """Every augment option of one piece, until ``max_matches`` rolls per option pass ``filters``."""
        r = self._start([str(armor_id)], filters, max_matches, limit)
        if "started" in r:
            self.save_settings({"armor": str(armor_id)})
        return r

    def scan_all_start(self, armor_ids: list, filters: dict, limit: int = 5_000_000):
        """First matching roll of every augment option on every listed piece (closest first)."""
        # Pieces that already have the skill would all match at roll #1: only augments that add it count.
        return self._start([str(a) for a in armor_ids], {**filters, "gainOnly": True}, 1, limit)

    # ---- ranking ------------------------------------------------------------------------------------

    def presets(self):
        """Built-in presets (read-only), the user's presets and every skill with how hard it is to get."""
        labels = {t: label for t, label, _ in ranking.TIERS}
        skills = []
        for sid in sorted(int(k) for k in self.data["skills"]):
            t = ranking.tier(self.data, sid)
            skills.append(dict(self._skill(sid), tier=t, tierLabel=labels[t], tierWeight=ranking.TIER_WEIGHT[t],
                               qurious=any(s == sid for s, _ in self.tables.skill_costs)))
        skills.sort(key=lambda x: x["name"].lower())
        return {"builtin": ranking.builtin_presets(self.data), "user": self.settings.get("presets") or [],
                "skills": skills, "defaultSlots": ranking.DEFAULT_SLOT_WEIGHTS}

    def save_presets(self, presets: list):
        self.save_settings({"presets": [p for p in presets if not p.get("builtin")]})
        return True

    def preset_export(self, preset: dict):
        return ranking.export_text(preset, self.data)

    def preset_import(self, text: str):
        preset, unknown = ranking.import_text(text or "", self.data)
        if not preset["weights"] and not any(preset["slots"]) and not preset["defense"]:
            return {"error": "No preset found in the text. Paste a preset exported by this app."}
        return {"preset": preset, "unknown": unknown}

    def rank_start(self, armor_ids: list, preset: dict, depth: int = 200):
        """Score the next ``depth`` rolls of every augment option on every listed piece; report the best
        roll of each piece and option (updated while the search runs)."""
        self.find_cancel()
        if not self.data or not self.generators:
            return {"error": "Select a hunter first."}
        ids = [str(a) for a in armor_ids if str(a) in self.data["armors"]]
        if not ids:
            return {"error": "No armor piece to rank."}
        if not any(float(w) for w in preset.get("weights", {}).values()) and not any(preset.get("slots", []))                 and not preset.get("defense"):
            return {"error": "Every weight of this preset is 0: give some skills a weight first."}
        depth = max(1, min(100_000, int(depth)))
        streams = [(aid, t) for aid in ids for t in engine.TYPE_NAMES]
        self._job = search.start(self.data, self.generators, streams, {}, depth + 1, depth,
                                  lambda aid, s, n: self._row(self.data["armors"][aid], n, s),
                                  rank={"preset": preset})
        return {"started": True, "streams": [{"armor": aid, "type": t} for aid, t in streams], "depth": depth}

    def find_status(self, since: int = 0):
        job = getattr(self, "_job", None)
        if not job:
            return {"done": True, "events": [], "total": 0, "depth": 0, "streams": {}}
        return job.snapshot(int(since))

    def find_cancel(self):
        job = getattr(self, "_job", None)
        if job and not job.done:
            job.cancel()
        return True

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
            "skills": [dict(self._skill(k), v=v) for k, v in _merge_skills(s.skills)],
        }


def main():
    import multiprocessing

    multiprocessing.freeze_support()  # search workers in the frozen exe
    import webview

    api = Api()
    webview.create_window(TITLE, WEB.as_uri(), js_api=api, width=1360, height=860, min_size=(1000, 600),
                          background_color="#14110d")
    webview.start()


if __name__ == "__main__":
    main()
