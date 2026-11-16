# Research probes (REFramework)

Lua scripts used to reconstruct the augment roll black-box. Copy one into
`<game>/reframework/autorun/`, load a hunter and follow the comments at the top of the file. They
restore every random generator they touch; still, **do not save the game** after running them.
Outputs land in `<game>/reframework/data/`.

| Script | What it records |
| --- | --- |
| `qurious_probe.lua` | type layouts, generator states, `via.Random` samples (`QuriousProbe.txt`) |
| `qurious_trace.lua` | inner lottery calls of `createResult` from known states (`QuriousTrace.txt`) |
| `qurious_bulk.lua` | `createResult` over 20,000 generator states × 4 options (`QuriousBulk.txt`) |
| `talisman_trace.lua` | melding: type dump (`TalismanTypes.txt`), passive trace of real melds (`TalismanTrace.txt`) and **Run active probe**, the game's melding lottery for every method on a private queue entry (`TalismanActive4.txt`) |

`talisman_trace.lua` hooks many methods and its active probe calls game functions: keep a save backup.
Calling the lottery with no picked skill on a method that needs one crashed the game, so the active
probe never does that.

`tests/test_validation.py` replays these recordings against the Python re-implementation.
