# MH Rise Qurious Predictor

Offline predictor for **Qurious Crafting** of armor (augments) in *Monster Hunter Rise: Sunbreak*
(PC/Steam). It reads your save and shows the **next augment results** of every qurious-capable armor
piece in the game (crafted or not) for each option of the game's menu: **Augment**,
**Augment: Stability**, **Augment: Skills+** and **Augment: Slots+**. Filters search ahead until they
find what you want (skills at a minimum level, with AND/OR, minimum slots, defense, no skill loss, no
negative resistance), one search can look through every armor piece at once, and a **Ranking** tab
scores every piece's next augments with weighted skill presets.

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

The game executable is packed, so nothing was disassembled: the algorithm was reconstructed
black-box, by calling the game's own functions through REFramework from known generator states.
See [docs/RESEARCH.md](docs/RESEARCH.md) and the scripts in [tools/probes](tools/probes).

## Accuracy

Validated against recordings from the game (`tests/test_validation.py`):

* 80,000 `createResult` calls from 20,000 random generator states, all four options: 80,000/80,000 identical;
* 160 calls traced in game, including the inner lottery functions: 160/160 identical;
* 3 × 458 consecutive rolls exported by the "Qurious Preview and Export as csv" mod: 1,374/1,374 identical;
* 5 real augments done in game: 5/5 identical.

Known gap: every recording used armor with augment cost 10. The generator used for costs 12–20
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
* RSZ type layouts: [kvasszn/ree-save-editor](https://github.com/kvasszn/ree-save-editor).
* [REFramework](https://github.com/praydog/REFramework), used for the research probes.
* [PyO3](https://pyo3.rs), [maturin](https://www.maturin.rs) and [rayon](https://github.com/rayon-rs/rayon)
  (MIT/Apache-2.0) for the Rust engine.
* The "Qurious Preview and Export as csv" REFramework mod (Nexus Mods), used as ground truth.

## License

MIT, see [LICENSE](LICENSE). Monster Hunter Rise © CAPCOM. This is an unofficial fan tool; no game
data is distributed, everything is read from your own install.
