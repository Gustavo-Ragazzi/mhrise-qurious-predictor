# MH Rise Qurious Predictor

Offline predictor for **Qurious Crafting** of armor (augments) in *Monster Hunter Rise: Sunbreak*
(PC/Steam). It reads your save and shows the **next augment results** of every qurious-capable armor
piece in the game (crafted or not) for each option of the game's menu: **Augment**,
**Augment: Stability**, **Augment: Skills+** and **Augment: Slots+**. Filters search ahead until they
find what you want (skills at a minimum level, with AND/OR, minimum slots, defense, no skill loss, no
negative resistance), one search can look through every armor piece at once, and a **Ranking** tab
scores every piece's next augments with weighted skill presets. A **Talismans** tab predicts the
next talismans of every Melding Pot method. Under **My equipment**, an **Inventory** ranks the armor
and talismans you own, a **Build optimizer** improves a loadout of your save, and **Export** writes
your talismans, armor and decorations (wiki-db import lines, CSV or JSON). The **Set builder** is a
skill simulator that also counts future qurious augments and talismans: it finds the armor set
that needs the fewest rolls.

The game does not need to be running and no mod is needed. The save is only read, never written.

## Download

Get `MHRiseQuriousPredictor-<version>-windows.zip` from the
[Releases](../../releases) page, unzip and run `MHRiseQuriousPredictor.exe`. No installation and no
Python needed. The window uses Microsoft Edge WebView2, which ships with Windows 10/11.

The executable is not code-signed, so Windows SmartScreen may warn on first launch
("More info" → "Run anyway").

The app finds the game and your Steam saves on its own (any Steam account on the PC); use
**Game folder…** if the game is installed somewhere unusual. On first launch it reads the game
data and icons from your install (a few seconds) and caches them in
`%LOCALAPPDATA%\mhrise-qurious-predictor`.

## How to use

The window has three main tabs: **Predictions** (Selected piece, Search all listed armor, Ranking,
Talismans), **My equipment** (Inventory, Build optimizer, Export) and **Set builder**.

1. Pick your hunter. The list on the left has every qurious-capable armor piece (master rank),
   grouped by rarity; filter by name or skill, part and rarity, or switch on **Crafted only**.
2. **Selected piece**: click a piece and pick the augment option tab. The **Rolls** column counts augments: 1 is what
   that option gives on the next augment of this piece, 2 the one after, and so on (200 rolls by default; the
   value is remembered).
3. To look for something specific, add filters. A skill filter means "at least this level on the piece
   after the augment". **Add** requires one more skill (AND); **Or** accepts this skill instead of the
   last one added (for example *Frenzied Bloodlust ≥ Lv1 or Mail of Hellfire ≥ Lv1*). The search runs
   on every CPU core until it finds up to 50 matching rolls per option; matches appear as they are
   found.
4. **Search all listed armor**: with filters set, press **Search** to find, for every piece listed on
   the left and every augment option, the closest roll that passes them, closest first. Here a wanted
   skill must be added by the augment itself. Click a result to open that piece.
5. **Ranking**: pick a preset of skill weights on the left and press **Rank**. Every augment option of
   every piece (filtered by part, rarity and "Crafted only") is simulated for the next N rolls and the
   best roll of each piece and option is listed, sorted by **Score** (the piece after the augment: its
   skills, including the ones it loses, plus its slots) or by **Gain** (what the augment adds or
   removes); filter by augment option and minimum score, and click Rank, Score, Gain or Rolls to sort.
   The Ranking tab has its own filters (for example *Blood Awakening ≥ Lv1*: only rolls
   that keep or reach it are ranked). Presets can be created (every weight 0), cloned, renamed,
   deleted, and copied in or out as text with **Import** / **Export**.
6. Each roll shows the defense change, the resulting slots (qurious slots in green), the five
   resistances and the skills gained/lost.
7. **Talismans**: pick a melding method (and, for Reflecting Pool, Haze, Moonbow, Aurora and Qurious
   Cyclus, the skill you would pick) to list the next talismans it makes: skills, levels and slots.
   **Talismans** sets how far to look, up to 100,000,000 (20 million take a few seconds). Filter by **Skill 1** and **Skill 2** (each "any skill" or a skill at a minimum level, in either
   position, like the two skills a talisman can have) and minimum slots: only the matching talismans
   are listed. Each talisman has:
   * **Score**: its skills and slots weighted by a Ranking preset (**Score with**; skill rarity tiers
     and slot values as in the Ranking tab), and **Rank**, its place by score among all the simulated
     talismans (equal scores share a rank);
   * **Perfection**: its skill levels plus slot levels against the best talisman this method can make
     with the same skills (100% = **GOD**, a god charm); the three small bars under it are skill 1,
     skill 2 and slots.

   Click Talisman, Rank, Score or Perfection to sort: the 1,000 best rows for that sort are shown
   (filtering and sorting run on all the simulated talismans). Each method has its own sequence in the save,
   advanced once per talisman, whatever the materials or the number of talismans per meld; only that
   method moves it. Notes:
   * when the picked skill misses (its pick rate is below 100%), skill 1 is a random skill: marked
     *missed*;
   * Qurious Cyclus replaces a second skill equal to the picked one using a generator that is not in
     the save, so that second skill is shown as *?*;
   * the game keeps the last random skills of each queue slot in memory only: melding other methods in
     the same session before Aurora or Cyclus can, rarely, change their second skill. Right after
     loading the save the prediction is exact.

8. **Inventory**: every armor piece in your box (low, high and master rank, with its qurious augments
   applied: defense, resistances, slots and skill changes) and every talisman, scored with a Ranking
   preset (**Score with**). Armor gets a **Rank** among all your armor and a **Part rank** among your
   pieces of the same part; talismans get a **Rank** and a **Perfection** against the best talisman
   any melding method can make with the same skills (**Best from** names that method). Filter by
   part, name or skill, or **Qurious only**, and click the column titles to sort.

9. **Set builder** (a skill simulator like the one on mhrise.wiki-db.com): add the skills you want
   and their levels, the weapon's decoration slots and the armor ranks, then **Search**. It looks
   through game armor (to craft), your own armor with its qurious augments and your talismans, and
   places decorations (every decoration, or **Only my decorations**: as many as you have, in the box
   and slotted). **My armor** / **My talismans** add what is in your box as it is; independently,
   with **Qurious rolls** = N every qurious-capable piece can also take any of its next N augments
   of each of the four options (Augment, Stability, Skills+, Slots+, on a copy without augments), and
   with **Talisman rolls** = N any of the next N talismans of Qurious Melding—Vigor and of Qurious
   Melding—Cyclus with any skill it can pick. There is no limit on N (it runs in Rust; very large
   values take longer). **Results** sets are listed (20 by default), fewest rolls first (equal rolls:
   the best defense, or the best score with a Ranking preset); the search stops at the **Time limit**
   and then says so. Click a wanted skill to change its level. The **Qurious** column shows what
   qurious crafting changes on each piece: the augments it already has, or the one to roll. A set's rolls are
   counted per sequence: two pieces with the same augment cost and option share one sequence, so
   augments #3 and #7 of it cost 7 rolls, not 10, and need different roll numbers. Below the set,
   **what to do** lists the pieces to craft, which augment to keep on which piece and which talisman
   to keep.
10. **Build optimizer**: pick a loadout (what you wear now or any My Set of the save) and a Ranking
    preset. **Keep** starts with the loadout's skills the preset weighs (edit it to drop or add
    skills); the weapon slots come from the loadout's weapon. **Optimize** lists the best set
    without rolls (your armor, talismans and decorations; also game armor to craft with **Other game
    armor**) and then sets that need more rolls and score more, so you can decide whether a few more
    augments or melds are worth it. Score = preset weight x level of every skill (capped at its max)
    plus the free slots; Gain is against the loadout as it is. Without rolls the search is exact;
    with rolls it searches sets one or two changes away from the loadout and from that best set, so
    the list is a set of suggestions, not every possible set.
11. **Saved sets & planner** (under Set builder): **Save set** on a Set builder result keeps it. Tick
    saved sets and press **Make plan** for a roadmap from the save as it is now: per sequence, which
    piece to augment how many times and which augment to keep, per Qurious Melding sequence how many
    talismans to meld and which to keep, the pieces to craft, and the cost (zenny, Amber Essence
    points, Kamura Points, melding points, talismans used up by Cyclus), with how many of each Amber
    Essence or melding material would pay it. What moves what: each augment cost and option has its
    own sequence (Slots+ never moves Skills+; cost 10 never moves cost 12), Vigor has one sequence and
    Cyclus one per grade of the picked skill. Inside a sequence the order matters: an augment moves it
    by a different amount depending on what it rolls and sometimes on the piece, so the planner walks
    each sequence with the pieces really augmented, finds every wanted result again (also after you
    rolled something else) and picks the order that needs the fewest augments. When a cheaper piece of
    the same cost gives the same result, the augments before a wanted one go on it.
12. **Export**: talismans or qurious armor as wiki-db import lines (the same `ExportedTalismans.txt`
    and `ExportedQuriousArmors.txt` MHRiseExporter writes), or talismans, all armor and decorations as
    CSV or JSON; **Copy** or **Save as…**.

### Built-in presets

Damage skills (Attack Boost, Weakness Exploit, Bloodlust, Mail of Hellfire, Burst, Coalescence...)
and Wirebug skills (Wirebug Whisperer, Wind Mantle, Frenzied Bloodlust) are in every preset, taken
from common Sunbreak endgame builds of all 14 weapons. Weapon skills are split by class, because
armor often pairs a skill of each (Handicraft 3 + Ammo Up 3) and only one of them helps you:

* **All skills (Blademaster + Gunner)**: everything, element skills included.
* **Blademaster** / **Gunner**: the class's own weapon skills (sharpness, guard, shelling, horns...
  or ammo, arrows, recoil, reload...) plus element skills.
* **Blademaster, no element** / **Gunner, no element**: without skills that only boost element
  (element attack, Critical Element, Element Exploit, Dragon Conversion, Teostra Blessing). Skills
  that boost raw and element (Mail of Hellfire, Coalescence, Burst, Dereliction) stay.

Their weights per skill level follow how hard the skill is to get, read from the game data:

| Tier | Weight | Example |
| --- | --- | --- |
| Armor only (no decoration, talisman or qurious) | 15 | Blood Awakening |
| Talisman, no decoration, not from qurious | 14 | Dereliction |
| Qurious can add it, no decoration | 13.5 | Mail of Hellfire, Wind Mantle |
| Decoration Lv4 | 13 | Bloodlust |
| Decoration Lv3 | 11 | Blood Rite |
| Decoration Lv2 | 10 | Weakness Exploit |
| Decoration Lv1 | 6 | Reload Speed |

Slots: a new Lv1 slot 7, Lv1→2 8, Lv2→3 9, Lv3→4 12 (so a Lv4 slot is worth 36).

**The sequence is shared.** All armor pieces with the same augment cost (10, 12, … 20) and the same
augment option use one sequence. Augmenting any of them moves it forward, so after augmenting:
save in game, then press **Reload save**. Other options and costs are not affected.

## How it works

The game decides augments with its own pseudo-random generators, one per augment cost and option
(`FacilityDataManager.RandomSeedManual.CustomBuildup_TT_YY`), whose states are stored in the
character save. This tool:

1. decrypts the save (via [mhrise-exporter](https://github.com/Gustavo-Ragazzi/mhrise-exporter))
   and reads the 56 generator states;
2. re-implements the generator (`via.Random`, a xorshift128 with shifts 15/4/21) and
   `ArmorCustomBuildupData.createResult`, the game's augment roll. The reference version is Python
   (`qurious_predictor/engine.py`); searches run on a Rust port of it (`native/core`, loaded through
   PyO3) on every CPU core, several million rolls per second;
3. reads the augment tables (weights, costs, values), skill data and GUI icons from your own install.

Talismans work the same way: every Melding Pot method has its own generator in the save
(`RandomSeedManual.MakaAlchemy*`; Qurious Cyclus has one per grade of the picked skill), and
`qurious_predictor/melding.py` re-implements the game's melding lottery (`snow.data.alchemy.ReserveFunc`
and `LotFunc`) on the melding tables read from your install. The Talismans tab runs the Rust port
(`native/core/src/melding.rs`, about 5 million talismans per second), which filters, scores and sorts
in place and returns only the rows shown; the Python version is the reference it is tested against.

The Set builder and the Build optimizer run `native/core/src/sets.rs`, an exact branch and bound
adapted from mhrise-set-builder: candidates per part (dominated ones dropped), bounds on the wanted
skill levels (decorations included) and on the value, and an exact decoration placement at each
complete set. Future augments and talismans are candidates that cost rolls of their sequence; a later
roll of a piece is dropped when an earlier one already gives at least the same wanted skills and slots,
and the roll budget grows step by step (0, 1, 2, 3, 5, 8...) so close sets are found and proven quickly. Searches stop
after 20 seconds and then say so. Tests compare it with a brute force on random sets and check every
set found against the engine's own predictions (`tests/test_sets.py`).

The game executable is packed, so nothing was disassembled: the algorithm was reconstructed
black-box, by calling the game's own functions through REFramework from known generator states.
See [docs/RESEARCH.md](docs/RESEARCH.md) and the scripts in [tools/probes](tools/probes).

## Accuracy

Validated against recordings from the game (`tests/test_validation.py`):

* 80,000 `createResult` calls from 20,000 random generator states, all four options: 80,000/80,000 identical;
* 160 calls traced in game, including the inner lottery functions: 160/160 identical;
* 3 × 458 consecutive rolls exported by the "Qurious Preview and Export as csv" mod: 1,374/1,374 identical;
* 5 real augments done in game: 5/5 identical.

Talismans (`tests/test_melding.py`, recordings in `tests/data/melding_samples.json`): the game's own
melding lottery run with `tools/probes/talisman_trace.lua` from known generator states (about 5,500
talismans checked during the research, 1,960 kept as test data) plus 6 talismans from real Qurious
Vigor melds: every talisman identical for all 10 methods, except Qurious Cyclus when its second skill
falls back to an unsaved generator (about 1 in 100, flagged by the app).

Known gap (armor): every recording used armor with augment cost 10. The generator used for costs 12–20
follows the game's enum layout (`CustomBuildup_01_01` … `CustomBuildup_06_04`) but has not been
confirmed in game yet.

## Run from source

Needs Python 3.10+ and a [Rust toolchain](https://rustup.rs) (the install builds the engine with
[maturin](https://www.maturin.rs)):

```bash
python -m venv .venv
.venv/Scripts/pip install -e .[dev]
.venv/Scripts/python -m qurious_predictor
```

After changing the Rust code, run `pip install -e .` again. Without the compiled engine the app falls
back to the (slower) Python one; `QURIOUS_ENGINE=python` forces it.

Tests: `.venv/Scripts/python -m pytest` and `cargo test --manifest-path native/Cargo.toml`. The Rust
engine is compared roll by roll, generator state included, with the Python one on synthetic tables;
with the game (`MHR_GAME_DIR`) also on every armor piece, and with the recordings
(`MHR_QURIOUS_DATA` = a folder with the probe outputs) on the in-game traces. Tests that need the
game or the recordings are skipped otherwise.

Build the executable (also done by GitHub Actions on `v*` tags):

```bash
.venv/Scripts/python scripts/build.py
```

## Credits

* Save decryption and PAK/RSZ readers: mhrise-exporter, which ports
  [jinghaihan/mhrise-save-converter](https://github.com/jinghaihan/mhrise-save-converter) (MIT) and
  [wwylele/mhrice](https://github.com/wwylele/mhrice) (MIT/Apache-2.0); icon formats and the skill
  icon location also come from mhrice.
* RSZ type layouts: [kvasszn/ree-save-editor](https://github.com/kvasszn/ree-save-editor) and
  [alphazolam/RE_RSZ](https://github.com/alphazolam/RE_RSZ) (melding tables of the final game version).
* [REFramework](https://github.com/praydog/REFramework), used for the research probes.
* The set search, weapon layouts and armor upgrade tables follow mhrise-set-builder (same author).
* [PyO3](https://pyo3.rs), [maturin](https://www.maturin.rs) and [rayon](https://github.com/rayon-rs/rayon)
  (MIT/Apache-2.0) for the Rust engine.
* The "Qurious Preview and Export as csv" REFramework mod (Nexus Mods), used as ground truth.

## License

MIT, see [LICENSE](LICENSE). Monster Hunter Rise © CAPCOM. This is an unofficial fan tool; no game
data is distributed, everything is read from your own install.
