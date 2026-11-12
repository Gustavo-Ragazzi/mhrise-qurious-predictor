# MH Rise Qurious Predictor

Offline predictor for **Qurious armor crafting** (armor augments) in *Monster Hunter Rise: Sunbreak*
(PC/Steam). It reads your save file, finds every qurious-capable armor piece in your box, and shows
the **next augment results** for each augment type: Defense+, Skills+, Slots+ and Stability.

The game does not need to be running and no mod is needed. The save is only read, never written.

## How it works

The game decides augments with its own pseudo-random generators, one per augment cost tier and
augment type (`FacilityDataManager.RandomSeedManual.CustomBuildup_TT_YY`). Their current states are
stored in the character save. This tool:

1. decrypts the save (via [mhrise-exporter](https://github.com/Gustavo-Ragazzi/mhrise-exporter))
   and reads the 56 generator states;
2. re-implements the generator (`via.Random`, a xorshift128 with shifts 15/4/21) and
   `ArmorCustomBuildupData.createResult`, the game's augment roll;
3. reads the augment tables (weights, costs, values) from your own game install.

The sequence of results is **shared** by all armor pieces with the same augment cost and type.
Augmenting any of them advances it, so reload the save after each augment (save in game first).

See [docs/RESEARCH.md](docs/RESEARCH.md) for how the algorithm was reconstructed and validated.

## Run

```bash
python -m venv .venv
.venv/Scripts/pip install -e ../mhrise-exporter -e .
.venv/Scripts/python -m qurious_predictor
```

## Accuracy

Validated against recordings from the game (`tests/test_validation.py`):

* 160 `createResult` calls traced in game from known generator states: 160/160 identical;
* 3 × 458 consecutive rolls exported by the "Qurious Preview and Export as csv" mod
  (Defense+, Slots+ and Stability, cost-10 armor): 1374/1374 identical;
* 5 real Slots+ augments: 5/5 identical.

Known gaps: the generator used for armor with augment cost 12–20 follows the game's enum layout
but has not been confirmed in game yet (all recordings used cost-10 armor).

## Credits

* Save decryption and PAK/RSZ readers: mhrise-exporter, which ports
  [jinghaihan/mhrise-save-converter](https://github.com/jinghaihan/mhrise-save-converter) (MIT) and
  [wwylele/mhrice](https://github.com/wwylele/mhrice) (MIT/Apache-2.0).
* RSZ type layouts: [kvasszn/ree-save-editor](https://github.com/kvasszn/ree-save-editor).
* The "Qurious Preview and Export as csv" REFramework mod, used as ground truth.

Monster Hunter Rise © CAPCOM. No game data is distributed; everything is read from your install.
