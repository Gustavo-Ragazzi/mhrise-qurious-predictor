# How the qurious augment roll was reconstructed

The game executable is packed, so its code was not disassembled. Everything here comes from
black-box observation through REFramework scripts (`tools/probes` in mhrise-set-builder):
calling the game's own functions from known generator states and comparing inputs and outputs.

## Random generator (`via.Random`)

* State: 4 × u32, exposed as `StateId` (a GUID).
* `genU32()`: `t = x ^ (x << 15); x, y, z = y, z, w; w = w ^ (w >> 21) ^ t ^ (t >> 4); return w`.
* `genF32()` = `genU32() / 2^32`.
* `FacilityDataManager._RandomManual` holds 56 generators (enum `RandomSeedManual`).
  `GuiCustomBuildup.calcRandomSeed(cost)` uses `32 + type + tier * (3 - type)`, where
  `tier = trunc((cost - 10) / 2)` (0..5; otherwise generator 18). The enum names do **not**
  describe this arithmetic. Normal/Skills+/Slots+ have strides 3/2/1, and Stability always
  uses 35. Cost 12 shares generator 35 across all four options. Confirmed by reading the
  game's selector and by a Kaiser Crown X normal augment moving only generator 35:
  `(2751145438,2451486738,3155500154,666053897)` ->
  `(3155500154,666053897,364268471,3611330697)`, yielding defense +16 only.
  Plans must group by generator and walk each step with its own option and cost.
  All 56 states are saved in `FacilityDataManager.SaveData` as a GUID list.

Every weighted lot draws one `genU32()` and picks with `u % sum(weights)`.

## `ArmorCustomBuildupData.createResult(cost, …, buildupType, seed)`

Tables: `CustomBuildupArmorCategoryLotUserData` (category weights per table, `[40, 30, 10, 20]` for
Def/Res/Slot/Skill), `CustomBuildupArmorLotUserData` (buildup weights per category),
`CustomBuildupBaseUserData` (cost, values, value weights), `CustomBuildupEquipSkillDetailUserData`
(skill pool by cost), `PlEquipSkillBaseData` (skill max levels, 0-based).

`remaining = cost`; repeat up to 52 lots:

1. When 6 entries exist, the 7th is a *fill*: the defense buildup with the highest cost
   `<= remaining`, without a lot (its value index is still lotted). If the defense total becomes 0,
   all defense entries are removed and lotting continues; otherwise the roll ends.
2. Category: forced for the first lots of each type (below), otherwise lotted. Stability turns a
   Skill result into Defense.
3. Buildup: forced id list or lotted among the category's entries with weight > 0 (Stability only
   positive-cost ones). A single candidate takes no draw.
4. Value index: lotted only when more than one value weight is non-zero.
5. Skill: `+1` picks from the skills whose cost equals the buildup cost (`u % n`); `-1` picks one of
   the armor's skills (`u % n`).
6. Rejected (draws already spent) when: cost > remaining; skill `-1` more times than the armor's
   level; skill `+1` beyond the skill's max level; a skill `+1` of a skill the piece does not have
   when the piece is out of skill slots (a piece holds 5 skills: the armor's own plus one per entry of
   a new skill; raising an already added skill again is allowed). The forced Skills+ skill is lotted
   again when it is the skill the forced `-1` just removed. The same skill can get `+1` more than once
   in one augment.
7. Accepted entries reduce `remaining`. If a group sums to 0 (all defense, one element's
   resistance, one skill), the whole group is removed and its cost refunded.
8. The roll ends when `remaining <= 0`. A dropped group refunds its costs, which can leave `remaining`
   below 0 (a skill's forced `-1`, cost -10, cancelled by a later `+1` of it, cost 6): the roll ends
   there too (seen in game on Flaming Espinas Grip, Slots+; `tests/test_real_rolls.py`).

| type | forced lots |
| --- | --- |
| 0 Augment | Def (lotted), Skill (lotted) |
| 1 Skills+ | Skill −1 (149), resistance penalty −7 (lotted element), skill +1 of cost 9/12/15 |
| 2 Slots+ | Skill −1 (149), Def −25 (61), slot +1/+2 (139/140) |
| 3 Stability | Def (lotted); then no Skill, no negative buildups |
