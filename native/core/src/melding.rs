//! Talisman melding (Melding Pot) simulation: a line-by-line port of `qurious_predictor/melding.py`
//! (the reference, validated against the game; see its docstring for the algorithm), plus `scan`,
//! which runs millions of talismans and keeps only what the app shows.

use std::cmp::Ordering;
use std::collections::{BinaryHeap, HashMap};

use crate::Rng;

/// AlchemyPatturnData.convertAlchemyTypeToIndex order.
pub const ORDER: [i32; 10] = [0, 1, 2, 3, 4, 7, 8, 9, 10, 11];
const NO_GRADE: i32 = 4;
const CYCLUS_GENERATOR: usize = 25;

pub fn is_targeted(m: i32) -> bool {
    matches!(m, 0 | 1 | 2 | 9 | 11)
}

pub fn is_qurious(m: i32) -> bool {
    matches!(m, 10 | 11)
}

fn method_index(m: i32) -> usize {
    ORDER.iter().position(|&x| x == m).expect("known method")
}

fn slot_table(m: i32) -> usize {
    match m {
        7 => 5,
        8 => 7,
        9 => 6,
        _ => m as usize,
    }
}

/// FacilityDataManager._RandomManual index of a method (Cyclus: by the grade of the picked skill).
pub fn generator_index(m: i32, target_grade: Option<i32>) -> Option<usize> {
    match m {
        0..=4 => Some(m as usize),
        7 => Some(11),
        8 => Some(12),
        9 => Some(13),
        10 => Some(23),
        11 => target_grade.map(|g| CYCLUS_GENERATOR + g as usize),
        _ => None,
    }
}

/// Weighted lot: v = u % total, first entry whose running sum reaches v (inclusive), zero weights skipped.
#[inline]
pub fn lot(weights: &[u32], u: u32) -> Option<usize> {
    let total: u64 = weights.iter().map(|&w| w as u64).sum();
    if total == 0 {
        return None;
    }
    let v = u as u64 % total;
    let mut acc = 0u64;
    for (i, &w) in weights.iter().enumerate() {
        acc += w as u64;
        if w != 0 && v <= acc {
            return Some(i);
        }
    }
    None
}

fn top_level(rates: &[u32]) -> i32 {
    rates.iter().enumerate().filter(|(_, &w)| w != 0).map(|(i, _)| i as i32 + 1).max().unwrap_or(0)
}

#[derive(Clone, Debug)]
pub struct Row {
    pub skill: i32,
    pub grade: i32,
    pub pick_rate: u32,
    pub grade_pick: [u32; 2],
    pub skill1: Vec<u32>,
    pub miss: Vec<u32>,
    pub skill2: Vec<u32>,
}

/// SlotNumTable row: (grade 1, grade 2, the 8 per-method probability tables).
pub type SlotParams = (i32, i32, Vec<Vec<u32>>);

pub struct MeldTables {
    pub rows: HashMap<i32, Vec<Row>>,
    /// method -> (Probability1List, ProbabilityList, Probability2List)
    pub grades: HashMap<i32, [Vec<u32>; 3]>,
    /// skill 1 grade -> second skill chance per method index
    pub second: HashMap<i32, Vec<u32>>,
    /// slot index -> [(grade 1, grade 2, 8 probability tables)]
    pub slots: Vec<Vec<SlotParams>>,
    /// MysterySlotNumTable: (pick rate, slot levels)
    pub mystery: Vec<(u32, Vec<i32>)>,
}

impl MeldTables {
    fn slot_probs(&self, k: usize, g1: i32, g2: i32, m: i32) -> Option<&[u32]> {
        self.slots.get(k)?.iter().find(|q| q.0 == g1 && q.1 == g2).map(|q| q.2[slot_table(m)].as_slice())
    }

    /// Largest total of slot levels the method can give a talisman with these skill grades.
    pub fn best_slots(&self, m: i32, g1: i32, g2: i32) -> i32 {
        if is_qurious(m) {
            return self.mystery.iter().filter(|(w, _)| *w != 0).map(|(_, l)| l.iter().sum::<i32>()).max().unwrap_or(0);
        }
        fn best(t: &MeldTables, m: i32, g1: i32, g2: i32, k: usize) -> i32 {
            if k == 3 {
                return 0;
            }
            let Some(probs) = t.slot_probs(k, g1, g2, m) else { return 0 };
            probs
                .iter()
                .enumerate()
                .filter(|(lv, &w)| w != 0 && *lv != 0)
                .map(|(lv, _)| lv as i32 + if lv == 4 { 0 } else { best(t, m, g1, g2, k + 1) })
                .max()
                .unwrap_or(0)
        }
        best(self, m, g1, g2, 0)
    }

    pub fn best_second_level(&self, m: i32) -> i32 {
        let rows = &self.rows[&m];
        rows.iter()
            .filter(|r| !is_qurious(m) || r.grade_pick[1] != 0)
            .map(|r| top_level(&r.skill2))
            .max()
            .unwrap_or(0)
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Talisman {
    pub skills: Vec<(i32, i32)>,
    pub slots: [i32; 3],
    pub missed: bool,
    pub unsure: bool,
    pub best: [i32; 3],
}

impl Talisman {
    pub fn perfection(&self) -> f64 {
        let have: i32 = self.skills.iter().map(|s| s.1).sum::<i32>() + self.slots.iter().sum::<i32>();
        let top: i32 = self.best.iter().sum();
        if top == 0 { 0.0 } else { have as f64 / top as f64 }
    }
}

/// A slot of ReserveInfo.RandomSkillTableList: a row of this method, or (carried over from another
/// method) just a skill id.
#[derive(Clone, Copy, Debug, PartialEq)]
enum Entry {
    Row(usize),
    Foreign(i32),
}

pub struct Melder<'a> {
    t: &'a MeldTables,
    m: i32,
    rows: &'a [Row],
    target: Option<usize>,
    table: [Option<Entry>; 2],
    slot0: [Vec<usize>; 4],
    slot1: [Vec<usize>; 4],
    best_slots: [[i32; 5]; 4],
    best_second: i32,
    mystery_weights: Vec<u32>,
    buf: Vec<usize>,
    wbuf: Vec<u32>,
}

impl<'a> Melder<'a> {
    pub fn new(t: &'a MeldTables, m: i32, target_skill: Option<i32>, previous: [Option<i32>; 2]) -> Result<Self, String> {
        let rows: &[Row] = t.rows.get(&m).map(|v| v.as_slice()).ok_or_else(|| format!("unknown melding method {m}"))?;
        let target = if is_targeted(m) {
            let i = rows.iter().position(|r| r.pick_rate > 0 && Some(r.skill) == target_skill);
            Some(i.ok_or_else(|| "pick a skill for this melding method".to_string())?)
        } else {
            None
        };
        let entry = |sid: Option<i32>| sid.map(|s| rows.iter().position(|r| r.skill == s).map(Entry::Row).unwrap_or(Entry::Foreign(s)));
        let mut slot0: [Vec<usize>; 4] = Default::default();
        let mut slot1: [Vec<usize>; 4] = Default::default();
        for (i, r) in rows.iter().enumerate() {
            if !(0..4).contains(&r.grade) {
                continue;
            }
            let g = r.grade as usize;
            let s0 = if is_qurious(m) {
                r.grade_pick[0] != 0
            } else if is_targeted(m) {
                r.miss.iter().any(|&w| w != 0)
            } else {
                r.skill1.iter().any(|&w| w != 0)
            };
            if s0 {
                slot0[g].push(i);
            }
            let s1 = if is_qurious(m) { r.grade_pick[1] != 0 } else { r.skill2.iter().any(|&w| w != 0) };
            if s1 {
                slot1[g].push(i);
            }
        }
        let mut best_slots = [[0; 5]; 4];
        for (g1, row) in best_slots.iter_mut().enumerate() {
            for (g2, v) in row.iter_mut().enumerate() {
                *v = t.best_slots(m, g1 as i32, g2 as i32);
            }
        }
        Ok(Melder {
            t,
            m,
            rows,
            target,
            table: [entry(previous[0]), entry(previous[1])],
            slot0,
            slot1,
            best_slots,
            best_second: t.best_second_level(m),
            mystery_weights: t.mystery.iter().map(|x| x.0).collect(),
            buf: Vec::with_capacity(64),
            wbuf: Vec::with_capacity(64),
        })
    }

    pub fn target_grade(&self) -> Option<i32> {
        self.target.map(|i| self.rows[i].grade)
    }

    fn skill_of(&self, e: Entry) -> i32 {
        match e {
            Entry::Row(i) => self.rows[i].skill,
            Entry::Foreign(s) => s,
        }
    }

    /// Picks from self.buf (row indices): weighted by GradePickRate[col] for Qurious methods, else uniform.
    fn pick(&mut self, u: u32, col: usize) -> Option<usize> {
        if is_qurious(self.m) {
            self.wbuf.clear();
            let rows = self.rows;
            self.wbuf.extend(self.buf.iter().map(|&i| rows[i].grade_pick[col]));
            lot(&self.wbuf, u).map(|k| self.buf[k])
        } else {
            Some(self.buf[u as usize % self.buf.len()])
        }
    }

    fn update(&mut self, rng: &mut Rng) -> bool {
        let m = self.m;
        let grades = &self.t.grades[&m];
        let mut unsure = false;
        // slot 0
        let list = if is_targeted(m) { &grades[1] } else { &grades[0] };
        if let Some(g) = lot(list, rng.next_u32()) {
            if g < 4 && !self.slot0[g].is_empty() {
                self.buf.clear();
                self.buf.extend_from_slice(&self.slot0[g]);
                let u = rng.next_u32();
                if let Some(i) = self.pick(u, 0) {
                    self.table[0] = Some(Entry::Row(i));
                }
            }
        }
        // slot 1
        if let Some(g) = lot(&grades[2], rng.next_u32()) {
            if g < 4 {
                let ex0 = self.table[0].map(|e| self.skill_of(e));
                let ex1 = if is_qurious(m) { None } else { self.target.map(|i| self.rows[i].skill) };
                let rows = self.rows;
                self.buf.clear();
                self.buf.extend(self.slot1[g].iter().copied().filter(|&i| Some(rows[i].skill) != ex0 && Some(rows[i].skill) != ex1));
                if !self.buf.is_empty() {
                    let u = rng.next_u32();
                    let pick = self.pick(u, 1);
                    if let (true, Some(t), Some(p)) = (is_qurious(m), self.target, pick) {
                        if rows[p].skill == rows[t].skill {
                            unsure = true;
                        }
                    }
                    self.table[1] = pick.map(Entry::Row);
                }
            }
        }
        unsure
    }

    pub fn talisman(&mut self, rng: &mut Rng) -> Talisman {
        let m = self.m;
        let mut out = Talisman { unsure: self.update(rng), ..Default::default() };
        let (u_pick, u_level) = (rng.next_u32(), rng.next_u32());
        let (row, lv) = match self.target {
            Some(t) if u_pick % 100 < self.rows[t].pick_rate => (Some(t), lot(&self.rows[t].skill1, u_level)),
            _ => {
                out.missed = self.target.is_some();
                match self.table[0] {
                    Some(Entry::Row(i)) => {
                        let r = &self.rows[i];
                        (Some(i), lot(if out.missed { &r.miss } else { &r.skill1 }, u_level))
                    }
                    _ => (None, None),
                }
            }
        };
        let (Some(row), Some(lv)) = (row, lv) else { return out };
        let r1 = &self.rows[row];
        out.skills.push((r1.skill, lv as i32 + 1));
        let u = rng.next_u32();
        let second = match self.table[1] {
            Some(Entry::Row(i)) => Some(i),
            _ => None,
        };
        let chance = self.t.second.get(&r1.grade).map(|v| v[method_index(m)]).unwrap_or(0);
        if self.table[1].is_some() && u % 100 < chance {
            if let Some(i) = second {
                if let Some(lv2) = lot(&self.rows[i].skill2, rng.next_u32()) {
                    out.skills.push((self.rows[i].skill, lv2 as i32 + 1));
                }
            }
        } else {
            out.unsure = false;
        }
        let g1 = r1.grade;
        let g2 = if out.skills.len() > 1 { self.rows[second.unwrap()].grade } else { NO_GRADE };
        let mut slots: Vec<i32> = Vec::with_capacity(3);
        if is_qurious(m) {
            if let Some(k) = lot(&self.mystery_weights, rng.next_u32()) {
                slots.extend_from_slice(&self.t.mystery[k].1);
            }
        } else {
            for k in 0..3 {
                let Some(probs) = self.t.slot_probs(k, g1, g2, m) else { break };
                let level = lot(probs, rng.next_u32()).unwrap_or(0) as i32;
                if level == 0 {
                    break;
                }
                slots.push(level);
                if level == 4 {
                    break;
                }
            }
        }
        slots.sort_unstable_by(|a, b| b.cmp(a));
        for (k, lv) in slots.into_iter().take(3).enumerate() {
            out.slots[k] = lv;
        }
        let max1 = top_level(if out.missed { &r1.miss } else { &r1.skill1 });
        let gi = g1.clamp(0, 3) as usize;
        out.best = if out.skills.len() > 1 {
            [max1, top_level(&self.rows[second.unwrap()].skill2), self.best_slots[gi][g2 as usize]]
        } else if chance > 0 {
            let p2 = &self.t.grades[&m][2];
            let g2s: Vec<usize> = p2.iter().enumerate().filter(|(_, &w)| w != 0).map(|(g, _)| g).collect();
            let bs = if g2s.is_empty() { self.best_slots[gi][NO_GRADE as usize] } else { g2s.iter().map(|&g| self.best_slots[gi][g.min(4)]).max().unwrap() };
            [max1, self.best_second, bs]
        } else {
            [max1, 0, self.best_slots[gi][NO_GRADE as usize]]
        };
        out
    }
}

// ---- scan: filter, score, rank, keep the rows the app shows -------------------------------------------

/// Wanted skills (in either position, two different skills of the talisman) and minimum slots.
#[derive(Clone, Debug, Default)]
pub struct Filter {
    pub skills: Vec<(i32, i32)>,
    pub slots: [i32; 3],
}

impl Filter {
    pub fn active(&self) -> bool {
        !self.skills.is_empty() || self.slots.iter().any(|&s| s > 0)
    }

    pub fn matches(&self, t: &Talisman) -> bool {
        let mut used = [false; 2];
        for &(sid, lv) in &self.skills {
            let k = t.skills.iter().enumerate().position(|(i, s)| !used[i] && s.0 == sid && s.1 >= lv.max(1));
            match k {
                Some(i) => used[i] = true,
                None => return false,
            }
        }
        let mut need = self.slots;
        need.sort_unstable_by(|a, b| b.cmp(a));
        need.iter().zip(t.slots.iter()).all(|(n, h)| h >= n)
    }
}

/// Skill weights per level (by skill id) and slot values by level, as in the Ranking tab.
pub struct Scorer {
    pub weights: Vec<f64>,
    pub max_levels: Vec<i32>,
    pub slot_value: [f64; 5],
}

impl Scorer {
    pub fn new(weights: &[(i32, f64)], max_levels: &HashMap<i32, i32>, slot_value: [f64; 5]) -> Self {
        let n = 1 + weights.iter().map(|w| w.0).chain(max_levels.keys().copied()).max().unwrap_or(0).max(0) as usize;
        let mut w = vec![0.0; n];
        for &(s, v) in weights {
            if s >= 0 {
                w[s as usize] = v;
            }
        }
        let mut mx = vec![99; n];
        for (&s, &v) in max_levels {
            if s >= 0 {
                mx[s as usize] = v;
            }
        }
        Scorer { weights: w, max_levels: mx, slot_value }
    }

    /// Score x 100, rounded (the app shows it with two decimals).
    pub fn score(&self, t: &Talisman) -> i64 {
        let mut total = 0.0;
        for &(s, lv) in &t.skills {
            if let Some(&w) = self.weights.get(s as usize) {
                total += w * lv.min(self.max_levels[s as usize]) as f64;
            }
        }
        for &lv in &t.slots {
            total += self.slot_value[lv.clamp(0, 4) as usize];
        }
        (total * 100.0).round() as i64
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SortKey {
    N,
    Rank,
    Score,
    Perfection,
}

#[derive(Clone, Debug)]
pub struct Found {
    pub n: u64,
    pub talisman: Talisman,
    pub score: i64,
    pub perfection: f64,
    /// 1 + talismans (of every scanned one) with a higher score; equal scores share a rank.
    pub rank: u64,
}

pub struct ScanResult {
    pub scanned: u64,
    pub matches: u64,
    pub first_match: Option<u64>,
    pub rows: Vec<Found>,
}

struct Keep {
    key: f64,
    n: u64,
    item: Found,
}

impl PartialEq for Keep {
    fn eq(&self, o: &Self) -> bool {
        self.cmp(o) == Ordering::Equal
    }
}
impl Eq for Keep {}
impl PartialOrd for Keep {
    fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
        Some(self.cmp(o))
    }
}
impl Ord for Keep {
    /// "Greater" = worse (the max-heap top is the first row to drop).
    fn cmp(&self, o: &Self) -> Ordering {
        self.key.total_cmp(&o.key).then(self.n.cmp(&o.n))
    }
}

/// Simulates `count` talismans and returns the `limit` best matches for the sort (`dir` 1 = ascending,
/// -1 = descending; ties by talisman number), with their score rank among every scanned talisman.
#[allow(clippy::too_many_arguments)]
pub fn scan(
    melder: &mut Melder,
    rng: &mut Rng,
    count: u64,
    filter: &Filter,
    scorer: &Scorer,
    sort: SortKey,
    dir: i32,
    limit: usize,
    cancel: &dyn Fn() -> bool,
) -> ScanResult {
    let mut heap: BinaryHeap<Keep> = BinaryHeap::with_capacity(limit + 1);
    let mut hist: HashMap<i64, u64> = HashMap::new();
    let mut matches = 0u64;
    let mut first_match = None;
    let mut scanned = 0u64;
    let sign = if dir < 0 { -1.0 } else { 1.0 };
    for n in 1..=count {
        if n % 65536 == 0 && cancel() {
            break;
        }
        let t = melder.talisman(rng);
        scanned = n;
        let score = scorer.score(&t);
        *hist.entry(score).or_insert(0) += 1;
        if !filter.matches(&t) {
            continue;
        }
        matches += 1;
        first_match.get_or_insert(n);
        if limit == 0 {
            continue;
        }
        let perfection = t.perfection();
        let key = sign
            * match sort {
                SortKey::N => n as f64,
                SortKey::Rank => -(score as f64),
                SortKey::Score => score as f64,
                SortKey::Perfection => perfection,
            };
        if heap.len() == limit {
            let worst = heap.peek().unwrap();
            if key.total_cmp(&worst.key).then(n.cmp(&worst.n)) != Ordering::Less {
                continue;
            }
        }
        heap.push(Keep { key, n, item: Found { n, talisman: t, score, perfection, rank: 0 } });
        if heap.len() > limit {
            heap.pop();
        }
    }
    let mut higher: Vec<(i64, u64)> = hist.into_iter().collect();
    higher.sort_unstable_by_key(|x| std::cmp::Reverse(x.0));
    let mut above = HashMap::with_capacity(higher.len());
    let mut acc = 0u64;
    for (s, c) in higher {
        above.insert(s, acc);
        acc += c;
    }
    let mut rows: Vec<Found> = heap.into_sorted_vec().into_iter().map(|k| k.item).collect();
    for f in &mut rows {
        f.rank = 1 + above[&f.score];
    }
    ScanResult { scanned, matches, first_match, rows }
}
