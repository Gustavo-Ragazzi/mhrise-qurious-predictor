# How the qurious augment roll was reconstructed

The game executable is packed, so its code was not disassembled. Everything here comes from
black-box observation through REFramework scripts (`tools/probes` in mhrise-set-builder):
calling the game's own functions from known generator states and comparing inputs and outputs.

## Random generator (`via.Random`)

* State: 4 × u32, exposed as `StateId` (a GUID).
* `genU32()`: `t = x ^ (x << 15); x, y, z = y, z, w; w = w ^ (w >> 21) ^ t ^ (t >> 4); return w`.
* `genF32()` = `genU32() / 2^32`.
* `FacilityDataManager._RandomManual` holds 56 generators (enum `RandomSeedManual`).
  `CustomBuildup_TT_YY` = index `32 + (TT-1)*4 + (YY-1)`: TT = cost tier (cost 10, 12, … 20),
  YY = augment type. All 56 states are saved in `FacilityDataManager.SaveData` as a GUID list.

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
6. Rejected (draws already spent) when: cost > remaining; skill `+1` already added, already at
   max level on the armor, or a third skill `+1`; skill `-1` more times than the armor's level.
7. Accepted entries reduce `remaining`. If a group sums to 0 (all defense, one element's
   resistance, one skill), the whole group is removed and its cost refunded.
8. The roll ends when `remaining == 0`.

| type | forced lots |
| --- | --- |
| 0 Augment | Def (lotted), Skill (lotted) |
| 1 Skills+ | Skill −1 (149), resistance penalty −7 (lotted element), skill +1 of cost 9/12/15 |
| 2 Slots+ | Skill −1 (149), Def −25 (61), slot +1/+2 (139/140) |
| 3 Stability | Def (lotted); then no Skill, no negative buildups |
