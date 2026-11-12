"""Tkinter window: pick a hunter and an armor piece, see the next qurious augments per type."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from mhrise_exporter import core, steam

from . import engine, gamedata, savedata
from .predict import next_rolls

TITLE = "MH Rise Qurious Predictor"
ELEMENT_LABEL = {"fire": "Fire", "water": "Water", "thunder": "Thunder", "ice": "Ice", "dragon": "Dragon"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(TITLE)
        scale = float(self.tk.call("tk", "scaling")) / (96 / 72)  # 1.0 at 100% Windows scaling
        self.px = lambda v: int(v * scale)
        self.geometry(f"{self.px(1180)}x{self.px(680)}")
        self.minsize(self.px(900), self.px(500))
        import tkinter.font as tkfont
        line = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        ttk.Style(self).configure("Treeview", rowheight=int(line * 1.35))
        self.data = None          # gamedata dict
        self.tables = None
        self.generators = None
        self.owned = []           # [(armor dict, OwnedArmor)]
        self.accounts = steam.find_accounts()
        self.game_dir = steam.find_game_dir()
        self.lang = tk.StringVar(value="en")
        self.count = tk.IntVar(value=10)
        self.filter = tk.StringVar()
        self.status = tk.StringVar(value="")
        self._build()
        self.after(50, self._start)

    # ---- layout ---------------------------------------------------------------------------------

    def _build(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Hunter").pack(side="left")
        self.hunter = ttk.Combobox(top, state="readonly", width=46)
        self.hunter.pack(side="left", padx=(4, 12))
        self.hunter.bind("<<ComboboxSelected>>", lambda e: self._load_save())
        ttk.Button(top, text="Reload save", command=self._load_save).pack(side="left")
        ttk.Button(top, text="Game folder…", command=self._pick_game).pack(side="left", padx=6)
        ttk.Label(top, text="Rolls").pack(side="left", padx=(12, 2))
        spin = ttk.Spinbox(top, from_=1, to=200, width=5, textvariable=self.count, command=self._refresh_rolls)
        spin.pack(side="left")
        spin.bind("<Return>", lambda e: self._refresh_rolls())
        ttk.Label(top, text="Names").pack(side="left", padx=(12, 2))
        self.lang_box = ttk.Combobox(top, state="readonly", width=6, textvariable=self.lang)
        self.lang_box.pack(side="left")
        self.lang_box.bind("<<ComboboxSelected>>", lambda e: (self._fill_armor(), self._refresh_rolls()))

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8)

        left = ttk.Frame(body)
        body.add(left, weight=1)
        ent = ttk.Entry(left, textvariable=self.filter)
        ent.pack(fill="x")
        self.filter.trace_add("write", lambda *a: self._fill_armor())
        self.armor = ttk.Treeview(left, columns=("cost", "owned"), show="tree headings", selectmode="browse")
        self.armor.heading("#0", text="Armor (in your box)")
        self.armor.heading("cost", text="Cost")
        self.armor.heading("owned", text="Owned")
        self.armor.column("#0", width=self.px(230))
        self.armor.column("cost", width=self.px(45), anchor="center", stretch=False)
        self.armor.column("owned", width=self.px(55), anchor="center", stretch=False)
        self.armor.pack(fill="both", expand=True)
        self.armor.bind("<<TreeviewSelect>>", lambda e: self._refresh_rolls())

        right = ttk.Frame(body)
        body.add(right, weight=4)
        self.info = ttk.Label(right, text="", wraplength=self.px(820), justify="left")
        self.info.pack(fill="x", pady=(0, 4))
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)
        self.trees = {}
        for t in (engine.TYPE_DEFENSE, engine.TYPE_SKILL, engine.TYPE_SLOT, engine.TYPE_STABILITY):
            frame = ttk.Frame(self.tabs)
            self.tabs.add(frame, text=engine.TYPE_NAMES[t])
            tree = ttk.Treeview(frame, columns=("n", "def", "slots", "res", "skills"), show="headings")
            for col, text, w, anchor in [("n", "#", 40, "center"), ("def", "Defense", 70, "center"),
                                         ("slots", "Slots", 55, "center"), ("res", "Resistances", 220, "w"),
                                         ("skills", "Skills", 420, "w")]:
                tree.heading(col, text=text)
                tree.column(col, width=self.px(w), anchor=anchor, stretch=col in ("res", "skills"))
            sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=sb.set)
            tree.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            self.trees[t] = tree
        self.tabs.bind("<<NotebookTabChanged>>", lambda e: self._update_info())

        ttk.Label(self, textvariable=self.status, padding=(8, 4), foreground="#555").pack(fill="x")

    # ---- data -------------------------------------------------------------------------------------

    def _start(self):
        self.hunters = []
        for acc in self.accounts:
            try:
                hunters, _ = core.read_hunters(acc.save_dir, acc.steamid64)
            except Exception:
                continue
            for h in hunters:
                if h.used:
                    self.hunters.append((acc, h))
        labels = [f"{h.name}  (HR {h.hr} / MR {h.mr}) · slot {h.slot} · {acc.persona or acc.steamid64}"
                  for acc, h in self.hunters]
        self.hunter["values"] = labels
        if not self.game_dir:
            self.status.set("Monster Hunter Rise not found: choose the game folder.")
            return
        self._load_game()

    def _pick_game(self):
        d = filedialog.askdirectory(title="Monster Hunter Rise folder")
        if d:
            self.game_dir = Path(d)
            self._load_game()

    def _load_game(self):
        self.status.set("Reading game data (first run takes a few seconds)…")

        def work():
            try:
                data = gamedata.load(Path(self.game_dir), log=lambda m: None)
                self.after(0, lambda: self._game_loaded(data))
            except Exception as e:
                self.after(0, lambda: self.status.set(f"Cannot read game data: {e}"))
        threading.Thread(target=work, daemon=True).start()

    def _game_loaded(self, data):
        self.data = data
        self.tables = gamedata.tables(data)
        langs = sorted({l for n in data["skills"].values() for l in n})
        self.lang_box["values"] = langs
        if self.hunters and not self.hunter.get():
            self.hunter.current(0)
        self._load_save()

    def _load_save(self):
        if not self.data or self.hunter.current() < 0:
            if not self.hunters:
                self.status.set("No MH Rise save found on this PC.")
            return
        acc, h = self.hunters[self.hunter.current()]
        try:
            save = core.load_slot(acc.save_dir, acc.steamid64, h.slot)
            self.generators = savedata.manual_generators(save)
            owned = savedata.owned_armor(save)
        except Exception as e:
            messagebox.showerror(TITLE, f"Cannot read the save:\n{e}")
            return
        self.owned = [(self.data["armors"][str(o.armor_id)], o) for o in owned
                      if str(o.armor_id) in self.data["armors"]]
        self.status.set(f"{h.name}: {len(self.owned)} qurious-capable armor pieces. "
                        "Predictions use the save as it is now — save the game in town after augmenting, "
                        "then press Reload save.")
        self._fill_armor()

    # ---- views ------------------------------------------------------------------------------------

    def _name(self, names: dict) -> str:
        return names.get(self.lang.get()) or names.get("en") or next(iter(names.values()), "?")

    def _skill(self, sid: int) -> str:
        return self._name(self.data["skills"].get(str(sid), {})) if sid else "?"

    def _fill_armor(self):
        if not self.data:
            return
        sel = self.armor.selection()
        self.armor.delete(*self.armor.get_children())
        f = self.filter.get().lower()
        rows = sorted(self.owned, key=lambda x: (x[0]["cost"], self._name(x[0]["names"])))
        for a, o in rows:
            name = self._name(a["names"])
            if f and f not in name.lower():
                continue
            self.armor.insert("", "end", iid=str(o.armor_id), text=name, values=(a["cost"], o.count))
        if sel and self.armor.exists(sel[0]):
            self.armor.selection_set(sel[0])

    def _selected(self):
        sel = self.armor.selection()
        return self.data["armors"].get(sel[0]) if sel else None

    def _refresh_rolls(self):
        armor = self._selected()
        for tree in self.trees.values():
            tree.delete(*tree.get_children())
        if not armor or not self.generators:
            self._update_info()
            return
        try:
            n = max(1, min(500, int(self.count.get())))
        except (tk.TclError, ValueError):
            n = 10
        self.seeds = {}
        for t, tree in self.trees.items():
            seed, rolls = next_rolls(self.generators, self.tables, armor, t, n)
            self.seeds[t] = seed
            for r in rolls:
                s = r.summary
                res = ", ".join(f"{ELEMENT_LABEL[k]} {v:+d}" for k, v in s.resistances.items())
                skills = ", ".join(f"{self._skill(k)} {v:+d}" for k, v in s.skills)
                tree.insert("", "end", values=(r.n, f"{s.defense:+d}", f"+{s.slots}" if s.slots else "",
                                               res, skills))
        self._update_info()

    def _update_info(self):
        armor = self._selected()
        if not armor:
            self.info.config(text="Select an armor piece on the left.")
            return
        t = self.tabs.index(self.tabs.select())
        same = [self._name(a["names"]) for a, _ in self.owned if a["cost"] == armor["cost"]]
        self.info.config(text=(
            f"{self._name(armor['names'])} — cost {armor['cost']}, table {armor['table']}. "
            f"Roll #1 is the next {engine.TYPE_NAMES[t]} augment. The sequence is shared by every armor "
            f"piece with cost {armor['cost']} and this augment type ({len(same)} in your box): augmenting "
            "any of them advances it, so reload after each augment. Other augment types and costs are "
            "independent."))


def main():
    try:  # crisp text on high-DPI Windows displays
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    App().mainloop()


if __name__ == "__main__":
    main()
