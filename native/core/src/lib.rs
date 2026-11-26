//! Qurious crafting (armor augment) simulation for MH Rise: Sunbreak.
//!
//! A line-by-line port of `qurious_predictor/engine.py` (the reference, validated against the game:
//! see docs/RESEARCH.md), plus the filter matcher and the ranking scorer. Every behaviour of the
//! Python version is kept on purpose, including tie-breaking, because the generator must advance
//! exactly like the game's.

use std::collections::HashMap;

pub mod melding;
pub mod sets;

// snow.data.DataDef.CustomBuildupCategoryId
pub const CAT_DEF: i32 = 13;
pub const CAT_RES: i32 = 14;
pub const CAT_RES_PENALTY: i32 = 15;
pub const CAT_SLOT: i32 = 19;
pub const CAT_SKILL: i32 = 20;
const LOT_CATEGORIES: [i32; 4] = [CAT_DEF, CAT_RES, CAT_SLOT, CAT_SKILL];
const DEFAULT_CATEGORY_WEIGHTS: [u32; 4] = [40, 30, 10, 20];

pub const MAX_ENTRIES: usize = 7;
pub const MAX_SKILLS_PER_PIECE: usize = 5;
pub const MAX_LOTS: i32 = 52;

pub const TYPE_AUGMENT: i32 = 0;
pub const TYPE_SKILL: i32 = 1;
pub const TYPE_SLOT: i32 = 2;
pub const TYPE_STABILITY: i32 = 3;

const ID_SKILL_DOWN: i32 = 149;
const ID_DEF_PENALTY: i32 = 61;

fn forced_category(buildup_type: i32, k: i32) -> Option<i32> {
    match (buildup_type, k) {
        (TYPE_AUGMENT, 0) => Some(CAT_DEF),
        (TYPE_AUGMENT, 1) => Some(CAT_SKILL),
        (TYPE_SKILL, 0) => Some(CAT_SKILL),
        (TYPE_SKILL, 1) => Some(CAT_RES_PENALTY),
        (TYPE_SKILL, 2) => Some(CAT_SKILL),
        (TYPE_SLOT, 0) => Some(CAT_SKILL),
        (TYPE_SLOT, 1) => Some(CAT_DEF),
        (TYPE_SLOT, 2) => Some(CAT_SLOT),
        (TYPE_STABILITY, 0) => Some(CAT_DEF),
        _ => None,
    }
}

fn forced_ids(buildup_type: i32, k: i32) -> Option<&'static [i32]> {
    match (buildup_type, k) {
        (TYPE_SKILL, 0) => Some(&[ID_SKILL_DOWN]),
        (TYPE_SKILL, 2) => Some(&[146, 147, 148]),
        (TYPE_SLOT, 0) => Some(&[ID_SKILL_DOWN]),
        (TYPE_SLOT, 1) => Some(&[ID_DEF_PENALTY]),
        (TYPE_SLOT, 2) => Some(&[139, 140]),
        _ => None,
    }
}

/// FacilityDataManager.RandomSeedManual index used for an augment (CustomBuildup_TT_YY).
pub fn seed_index(cost: i32, buildup_type: i32) -> usize {
    let tier = (cost - 10).div_euclid(2);
    if !(0..=5).contains(&tier) {
        return 18;
    }
    (32 + tier * 4 + buildup_type) as usize
}

// ---- via.Random ------------------------------------------------------------------------------------

/// via.Random: xorshift128 with shifts 15/4/21; genU32 returns the new `w`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Rng {
    pub x: u32,
    pub y: u32,
    pub z: u32,
    pub w: u32,
}

impl Rng {
    pub fn new(state: [u32; 4]) -> Self {
        Rng { x: state[0], y: state[1], z: state[2], w: state[3] }
    }

    pub fn state(&self) -> [u32; 4] {
        [self.x, self.y, self.z, self.w]
    }

    #[inline]
    pub fn next_u32(&mut self) -> u32 {
        let t = self.x ^ (self.x << 15);
        self.x = self.y;
        self.y = self.z;
        self.z = self.w;
        self.w = self.w ^ (self.w >> 21) ^ t ^ (t >> 4);
        self.w
    }
}

// ---- tables ----------------------------------------------------------------------------------------

#[derive(Clone, Debug)]
pub struct Buildup {
    pub table: i32,
    pub id: i32,
    pub category: i32,
    pub cost: i32,
    pub values: Vec<i32>,
    pub lots: Vec<u32>,
}

#[derive(Clone, Debug)]
struct LotItem {
    id: i32,
    lot: u32,
    cost: i32,
    values: Vec<i32>,
    lots: Vec<u32>,
    positive_lots: usize,
}

#[derive(Clone, Debug, Default)]
struct TableData {
    /// (category, lot items in table order)
    categories: Vec<(i32, Vec<LotItem>)>,
    weights: Vec<u32>,
}

impl TableData {
    fn items(&self, category: i32) -> &[LotItem] {
        self.categories.iter().find(|(c, _)| *c == category).map(|(_, v)| v.as_slice()).unwrap_or(&[])
    }
}

/// The qurious tables needed by the simulation, pre-joined per armor table.
#[derive(Clone, Debug, Default)]
pub struct Tables {
    tables: HashMap<i32, TableData>,
    skills_by_cost: HashMap<i32, Vec<i32>>,
    pub max_levels: HashMap<i32, i32>, // 0-based, like _MaxLevel
    empty: TableData,
}

impl Tables {
    /// `armor_lots` = (table, category, buildup id, lot); `skill_costs` = (skill id, cost) in table order.
    pub fn new(
        base: Vec<Buildup>,
        armor_lots: Vec<(i32, i32, i32, u32)>,
        category_lots: HashMap<i32, Vec<u32>>,
        skill_costs: Vec<(i32, i32)>,
        max_levels: HashMap<i32, i32>,
    ) -> Self {
        let base: HashMap<(i32, i32), Buildup> = base.into_iter().map(|b| ((b.table, b.id), b)).collect();
        let mut tables: HashMap<i32, TableData> = HashMap::new();
        for (table, category, bid, lot) in armor_lots {
            let Some(b) = base.get(&(table, bid)) else { continue };
            let t = tables.entry(table).or_default();
            let item = LotItem {
                id: bid,
                lot,
                cost: b.cost,
                values: b.values.clone(),
                lots: b.lots.clone(),
                positive_lots: b.lots.iter().filter(|&&x| x > 0).count(),
            };
            match t.categories.iter_mut().find(|(c, _)| *c == category) {
                Some((_, v)) => v.push(item),
                None => t.categories.push((category, vec![item])),
            }
        }
        for (table, w) in category_lots {
            tables.entry(table).or_default().weights = w;
        }
        for t in tables.values_mut() {
            if t.weights.is_empty() {
                t.weights = DEFAULT_CATEGORY_WEIGHTS.to_vec();
            }
        }
        let mut skills_by_cost: HashMap<i32, Vec<i32>> = HashMap::new();
        for (skill, cost) in skill_costs {
            skills_by_cost.entry(cost).or_default().push(skill);
        }
        let empty = TableData { categories: vec![], weights: DEFAULT_CATEGORY_WEIGHTS.to_vec() };
        Tables { tables, skills_by_cost, max_levels, empty }
    }

    fn table(&self, table: i32) -> &TableData {
        self.tables.get(&table).unwrap_or(&self.empty)
    }
}

// ---- createResult ----------------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Entry {
    pub category: i32,
    pub id: i32,
    pub value: i32,
    pub skill: i32,
    pub cost: i32,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Group {
    Def,
    Res(i32),
    Skill(i32),
}

/// Python's `(id - 89) // 10`.
fn element_raw(id: i32) -> i32 {
    (id - 89).div_euclid(10)
}

/// `element_raw` used as a list index (negative indexes count from the end, like Python).
fn element_of(id: i32) -> usize {
    let e = element_raw(id);
    (if e < 0 { e + 5 } else { e }).clamp(0, 4) as usize
}

impl Entry {
    fn group(&self) -> Option<Group> {
        match self.category {
            CAT_DEF => Some(Group::Def),
            CAT_RES => Some(Group::Res(element_raw(self.id))),
            CAT_SKILL => Some(Group::Skill(self.skill)),
            _ => None,
        }
    }
}

#[inline]
fn pick_index(weights: impl Iterator<Item = u32> + Clone, rng: &mut Rng) -> Option<usize> {
    let total: u64 = weights.clone().map(|w| w as u64).sum();
    if total == 0 {
        return None;
    }
    let r = rng.next_u32() as u64 % total;
    let mut acc = 0u64;
    let mut last = 0;
    for (i, w) in weights.enumerate() {
        acc += w as u64;
        if r < acc {
            return Some(i);
        }
        last = i;
    }
    Some(last)
}

/// `_pick(LOT_CATEGORIES, weights)`: the total covers every weight, the walk only the 4 categories.
fn pick_category(weights: &[u32], rng: &mut Rng) -> Option<i32> {
    let total: u64 = weights.iter().map(|&w| w as u64).sum();
    if total == 0 {
        return None;
    }
    let r = rng.next_u32() as u64 % total;
    let mut acc = 0u64;
    for (c, &w) in LOT_CATEGORIES.iter().zip(weights.iter()) {
        acc += w as u64;
        if r < acc {
            return Some(*c);
        }
    }
    Some(LOT_CATEGORIES[3])
}

#[inline]
fn value_index(item: &LotItem, rng: &mut Rng) -> usize {
    if item.positive_lots <= 1 {
        return 0;
    }
    pick_index(item.lots.iter().copied(), rng).unwrap_or(0)
}

fn drop_zero_group(res: &mut Vec<Entry>, remaining: &mut i32, group: Option<Group>) {
    let Some(g) = group else { return };
    let sum: i32 = res.iter().filter(|e| e.group() == Some(g)).map(|e| e.value).sum();
    if sum == 0 {
        for e in res.iter().filter(|e| e.group() == Some(g)) {
            *remaining += e.cost;
        }
        res.retain(|e| e.group() != Some(g));
    }
}

/// One augment roll; advances `rng` exactly like the game. `armor_skills` = (skill, level) in order.
pub fn create_result(
    rng: &mut Rng,
    tables: &Tables,
    table: i32,
    total_cost: i32,
    armor_skills: &[(i32, i32)],
    buildup_type: i32,
    res: &mut Vec<Entry>,
) {
    res.clear();
    let td = tables.table(table);
    let mut levels: Vec<(i32, i32)> = Vec::with_capacity(armor_skills.len());
    for &(s, lv) in armor_skills.iter().filter(|(s, _)| *s != 0) {
        match levels.iter_mut().find(|(x, _)| *x == s) {
            Some(e) => e.1 = lv,
            None => levels.push((s, lv)),
        }
    }
    let level_of = |s: i32| levels.iter().find(|(x, _)| *x == s).map(|e| e.1).unwrap_or(0);
    let has_level = |s: i32| levels.iter().any(|(x, _)| *x == s);
    let armor_ids: Vec<i32> = armor_skills.iter().filter(|(s, _)| *s != 0).map(|e| e.0).collect();
    let mut remaining = total_cost;

    let mut k: i32 = 0;
    while k < MAX_LOTS {
        if res.len() == MAX_ENTRIES - 1 {
            // Last entry: the largest defense buildup that fits (first one on ties), no lot.
            let mut best: Option<&LotItem> = None;
            for it in td.items(CAT_DEF) {
                if it.cost > 0 && it.cost <= remaining && best.map_or(true, |b| it.cost > b.cost) {
                    best = Some(it);
                }
            }
            let Some(b) = best else { break };
            let vi = value_index(b, rng);
            res.push(Entry { category: CAT_DEF, id: b.id, value: b.values[vi], skill: 0, cost: b.cost });
            remaining -= b.cost;
            let def: i32 = res.iter().filter(|e| e.category == CAT_DEF).map(|e| e.value).sum();
            if def == 0 {
                drop_zero_group(res, &mut remaining, Some(Group::Def));
                continue;
            }
            break;
        }

        let category = match forced_category(buildup_type, k) {
            Some(c) => Some(c),
            None => pick_category(&td.weights, rng)
                .map(|c| if buildup_type == TYPE_STABILITY && c == CAT_SKILL { CAT_DEF } else { c }),
        };
        let forced = forced_ids(buildup_type, k);
        let items: &[LotItem] = category.map(|c| td.items(c)).unwrap_or(&[]);
        // Candidates as (index into items, weight).
        let mut cands: Vec<(usize, u32)> = Vec::with_capacity(items.len());
        for (i, it) in items.iter().enumerate() {
            match forced {
                Some(ids) => {
                    if ids.contains(&it.id) {
                        cands.push((i, if it.lot > 0 { it.lot } else { 1 }));
                    }
                }
                None => {
                    if it.lot > 0 && (buildup_type != TYPE_STABILITY || it.cost > 0) {
                        cands.push((i, it.lot));
                    }
                }
            }
        }
        k += 1;
        if cands.is_empty() {
            continue;
        }
        let chosen = if cands.len() == 1 {
            cands[0].0
        } else {
            cands[pick_index(cands.iter().map(|c| c.1), rng).unwrap_or(0)].0
        };
        let b = &items[chosen];
        let category = category.unwrap();
        let vi = value_index(b, rng);
        let mut skill = 0;
        if category == CAT_SKILL {
            if b.cost > 0 {
                if let Some(pool) = tables.skills_by_cost.get(&b.cost).filter(|p| !p.is_empty()) {
                    skill = pool[(rng.next_u32() as usize) % pool.len()];
                }
            } else if !armor_ids.is_empty() {
                skill = armor_ids[(rng.next_u32() as usize) % armor_ids.len()];
            }
        }
        let mut ok = b.cost <= remaining;
        let mut conflict = false;
        if ok && category == CAT_SKILL {
            let adding = b.cost > 0;
            let same = res
                .iter()
                .filter(|e| e.category == CAT_SKILL && e.skill == skill && (e.cost > 0) == adding)
                .count() as i32;
            let removed = res.iter().any(|e| e.category == CAT_SKILL && e.cost < 0 && e.skill == skill);
            let added = res.iter().any(|e| e.category == CAT_SKILL && e.cost > 0 && e.skill == skill);
            if adding && forced.is_some() && removed {
                ok = false;
                conflict = true;
            }
            if !adding && same >= level_of(skill) {
                ok = false;
                conflict = false;
            }
            if adding && !has_level(skill) && !added {
                let used = levels.len()
                    + res.iter().filter(|e| e.category == CAT_SKILL && e.cost > 0 && !has_level(e.skill)).count();
                if used >= MAX_SKILLS_PER_PIECE {
                    ok = false;
                    conflict = false;
                }
            }
            if adding && level_of(skill) + same > tables.max_levels.get(&skill).copied().unwrap_or(99) {
                ok = false;
                conflict = false;
            }
        }
        if !ok && conflict {
            k -= 1; // the game repeats the forced lot
        }
        if ok {
            let entry = Entry { category, id: b.id, value: b.values[vi], skill, cost: b.cost };
            res.push(entry);
            remaining -= b.cost;
            drop_zero_group(res, &mut remaining, entry.group());
        }
        if remaining <= 0 {
            break;
        }
    }
}

// ---- summary, filters, scoring ---------------------------------------------------------------------

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Summary {
    pub defense: i32,
    pub slots: i32,
    /// fire, water, thunder, ice, dragon
    pub resistances: [i32; 5],
    /// (skill id, +1/-1) in entry order
    pub skills: Vec<(i32, i32)>,
}

pub fn summarize(entries: &[Entry]) -> Summary {
    let mut s = Summary::default();
    for e in entries {
        match e.category {
            CAT_DEF => s.defense += e.value,
            CAT_SLOT => s.slots += e.value,
            CAT_RES | CAT_RES_PENALTY => s.resistances[element_of(e.id)] += e.value,
            CAT_SKILL => s.skills.push((e.skill, e.value)),
            _ => {}
        }
    }
    s
}

/// `[n_lv1, n_lv2, n_lv3, n_lv4]` -> slot levels, highest first.
pub fn expand_slots(num_list: &[i32]) -> Vec<i32> {
    let mut out = Vec::new();
    for i in (0..num_list.len()).rev() {
        for _ in 0..num_list[i].max(0) {
            out.push(i as i32 + 1);
        }
    }
    out
}

/// Qurious slot points: a new Lv1 slot while the piece has fewer than 3, else raise the highest below 4.
pub fn apply_slot_bonus(base: &[i32], points: i32) -> Vec<i32> {
    let mut slots: Vec<i32> = base.to_vec();
    slots.sort_unstable_by(|a, b| b.cmp(a));
    for _ in 0..points.max(0) {
        if slots.len() < 3 {
            slots.push(1);
        } else if let Some(s) = slots.iter_mut().find(|s| **s < 4) {
            *s += 1;
        }
        slots.sort_unstable_by(|a, b| b.cmp(a));
    }
    slots
}

fn skill_delta(s: &Summary) -> Vec<(i32, i32)> {
    let mut d: Vec<(i32, i32)> = Vec::with_capacity(s.skills.len());
    for &(sid, v) in &s.skills {
        match d.iter_mut().find(|(x, _)| *x == sid) {
            Some(e) => e.1 += v,
            None => d.push((sid, v)),
        }
    }
    d
}

/// Filter of `search.matcher`: AND of OR groups of (skill, minimum level), and the other filters.
#[derive(Clone, Debug, Default)]
pub struct Filter {
    pub groups: Vec<Vec<(i32, i32)>>,
    pub min_slots: [i32; 3],
    pub min_def: Option<i32>,
    pub no_skill_loss: bool,
    pub no_negative_res: bool,
    pub gain_only: bool,
}

pub struct Matcher {
    filter: Filter,
    base_lv: Vec<(i32, i32)>,
    base_slots: Vec<i32>,
    min_slots: [i32; 3],
}

impl Matcher {
    pub fn new(armor_skills: &[(i32, i32)], slot_nums: &[i32], filter: Filter) -> Self {
        let mut min_slots = filter.min_slots;
        min_slots.sort_unstable_by(|a, b| b.cmp(a));
        Matcher { base_lv: armor_skills.to_vec(), base_slots: expand_slots(slot_nums), min_slots, filter }
    }

    fn base(&self, sid: i32) -> i32 {
        self.base_lv.iter().rev().find(|(s, _)| *s == sid).map(|e| e.1).unwrap_or(0)
    }

    pub fn matches(&self, s: &Summary) -> bool {
        let f = &self.filter;
        let delta = skill_delta(s);
        let d = |sid: i32| delta.iter().find(|(x, _)| *x == sid).map(|e| e.1).unwrap_or(0);
        for g in &f.groups {
            if !g.iter().any(|&(sid, level)| self.base(sid) + d(sid) >= level && (!f.gain_only || d(sid) > 0)) {
                return false;
            }
        }
        if f.no_skill_loss && delta.iter().any(|(_, v)| *v < 0) {
            return false;
        }
        if f.no_negative_res && s.resistances.iter().any(|v| *v < 0) {
            return false;
        }
        if let Some(m) = f.min_def {
            if s.defense < m {
                return false;
            }
        }
        if self.min_slots.iter().any(|x| *x != 0) {
            let mut fin = apply_slot_bonus(&self.base_slots, s.slots);
            fin.resize(fin.len().max(3), 0);
            if fin.iter().zip(self.min_slots.iter()).any(|(have, need)| have < need) {
                return false;
            }
        }
        true
    }
}

/// Ranking preset: weight per skill level (in preset order), per slot step and per defense point.
#[derive(Clone, Debug, Default)]
pub struct Preset {
    pub weights: Vec<(i32, f64)>,
    pub slot_steps: [f64; 4],
    pub defense: f64,
}

pub struct Scorer {
    weights: Vec<(i32, f64, i32)>, // (skill, weight, max level 1-based)
    slot_value: [f64; 5],
    def_w: f64,
    base_lv: Vec<(i32, i32)>,
    base_slots: Vec<i32>,
    pub base: f64,
}

impl Scorer {
    pub fn new(armor_skills: &[(i32, i32)], slot_nums: &[i32], preset: &Preset, max_levels: &HashMap<i32, i32>) -> Self {
        let st = preset.slot_steps;
        let weights = preset
            .weights
            .iter()
            .filter(|(_, w)| *w != 0.0)
            .map(|&(s, w)| (s, w, max_levels.get(&s).copied().unwrap_or(99) + 1))
            .collect();
        let mut sc = Scorer {
            weights,
            slot_value: [0.0, st[0], st[0] + st[1], st[0] + st[1] + st[2], st[0] + st[1] + st[2] + st[3]],
            def_w: preset.defense,
            base_lv: armor_skills.to_vec(),
            base_slots: expand_slots(slot_nums),
            base: 0.0,
        };
        let levels = sc.base_lv.clone();
        sc.base = sc.skills(&levels) + sc.slots(&sc.base_slots.clone());
        sc
    }

    fn skills(&self, levels: &[(i32, i32)]) -> f64 {
        self.weights
            .iter()
            .map(|&(s, w, max)| {
                let lv = levels.iter().rev().find(|(x, _)| *x == s).map(|e| e.1).unwrap_or(0);
                w * lv.clamp(0, max) as f64
            })
            .sum()
    }

    fn slots(&self, slots: &[i32]) -> f64 {
        slots.iter().map(|&lv| self.slot_value[lv.clamp(0, 4) as usize]).sum()
    }

    /// (score of the piece after the augment, gain over the piece before it)
    pub fn score(&self, s: &Summary) -> (f64, f64) {
        let mut levels = self.base_lv.clone();
        for &(sid, v) in &s.skills {
            match levels.iter_mut().rev().find(|(x, _)| *x == sid) {
                Some(e) => e.1 += v,
                None => levels.push((sid, v)),
            }
        }
        let mut total = self.skills(&levels) + self.def_w * s.defense as f64;
        total += if s.slots != 0 { self.slots(&apply_slot_bonus(&self.base_slots, s.slots)) } else { self.slots(&self.base_slots) };
        (total, total - self.base)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gen_u32_matches_game() {
        let mut r = Rng::new([0x8C947F67, 0xDE6FE7D0, 0x6EC4E2CC, 0x9F5B65EC]);
        let got: Vec<u32> = (0..6).map(|_| r.next_u32()).collect();
        assert_eq!(got, [659480967, 135362832, 373929392, 960366256, 1808511206, 3558563129]);
        assert_eq!(r.state(), [0x1649B5B0, 0x393E06B0, 0x6BCBB0E6, 0xD41B5D39]);
    }

    #[test]
    fn slot_bonus_rule() {
        assert_eq!(apply_slot_bonus(&[2], 1), vec![2, 1]);
        assert_eq!(apply_slot_bonus(&[3, 1, 1], 2), vec![4, 2, 1]);
        assert_eq!(expand_slots(&[0, 1, 0, 1]), vec![4, 2]);
    }

    #[test]
    fn seed_layout() {
        assert_eq!(seed_index(10, TYPE_SLOT), 34);
        assert_eq!(seed_index(20, TYPE_STABILITY), 55);
        assert_eq!(seed_index(8, 0), 18);
    }
}
