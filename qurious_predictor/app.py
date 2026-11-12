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
DEFAULT_SETTINGS = {"rolls": 200, "lang": "en", "hunter": None, "armor": None, "type": engine.TYPE_SKILL,
                    "wanted": [], "only_matches": False, "game_dir": None}


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
                "color": self.data["skill_colors"].get(str(sid), 0)}

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
            base = _expand_slots(a["slots"])
            out = {}
            for t in engine.TYPE_NAMES:
                seed, rolls = next_rolls(self.generators, self.tables, a, t, count)
                rows = []
                for r in rolls:
                    s = r.summary
                    new = (apply_slot_bonus(base, s.slots) + [0, 0, 0])[:3]
                    old = (sorted(base, reverse=True) + [0, 0, 0])[:3]
                    rows.append({
                        "n": r.n,
                        "def": s.defense,
                        "slotPoints": s.slots,
                        "slots": [{"lv": lv, "up": lv > ob} for lv, ob in zip(new, old)],
                        "res": [s.resistances.get(e, 0) for e in engine.ELEMENTS],
                        "skills": [dict(self._skill(k), v=v) for k, v in s.skills],
                    })
                out[t] = {"seed": seed, "rolls": rows}
            same = sum(1 for aid in self.owned if self.data["armors"][aid]["cost"] == a["cost"])
            return {"types": out, "sameCost": same}


def main():
    import webview

    api = Api()
    webview.create_window(TITLE, WEB.as_uri(), js_api=api, width=1360, height=860, min_size=(1000, 600),
                          background_color="#14110d")
    webview.start()


if __name__ == "__main__":
    main()
