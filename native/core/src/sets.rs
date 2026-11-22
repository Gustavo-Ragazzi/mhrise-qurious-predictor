//! Armor set search with roll costs: the set builder and the build optimizer.
//!
//! An exact branch and bound adapted from mhrise-set-builder (same author): depth first over
//! talisman → head → chest → arms → waist → legs, keeping the N best sets. Here a candidate piece
//! can also be a future qurious augment or a future talisman: it then costs rolls of one generator
//! (a "sequence"). Two pieces taken from the same sequence need different roll numbers, and a set
//! costs, per sequence, its highest roll number. An augment can draw from the generator a different
//! number of times on different pieces, so each piece has its own "stream" of a sequence: two pieces'
//! rolls fit in one set only when, after the earlier roll, both streams are still at the same place
//! (see `Sync`); the rolls before the first one are then spent on the first piece.
//!
//! Prunes:
//! - dominance per part before the search (same or fewer rolls, at least the requested skill
//!   levels, slot capacity and value);
//! - value bound: what the set has so far plus the best remaining candidates cannot beat the N-th
//!   best set (with `cost_first`, a set that needs more rolls never beats one that needs fewer);
//! - skill bound: the best remaining candidates plus decorations in every slot still possible cannot
//!   reach a requested level (Rise decorations have one skill each, which keeps this exact per skill).
//!
//! Leaves place decorations exactly (small DFS over cumulative slot capacity, honouring how many of
//! each decoration the hunter owns) leaving the biggest slots free; in score mode the free slots are
//! then filled greedily with decorations worth more than an empty slot.

use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashMap};
use std::sync::atomic::{AtomicBool, AtomicI64, AtomicU64, Ordering};
use std::time::Instant;

use rayon::prelude::*;

pub const MAX_REQ: usize = 24;

/// Set by the app to stop the running search (it then returns what it found, as if the deadline came).
pub static CANCEL: AtomicBool = AtomicBool::new(false);
/// Progress of the running search, for the app to show: combinations tried and the roll budget.
pub static PROGRESS_NODES: AtomicU64 = AtomicU64::new(0);
pub static PROGRESS_BUDGET: AtomicU64 = AtomicU64::new(0);
/// Nodes counted locally before they are added to `PROGRESS_NODES`.
const PROGRESS_EVERY: u64 = 4096;
const DEPTH: usize = 6; // talisman + 5 armor parts
/// Rolled dominators (with different rolls) needed to drop a candidate; see `prune_dominated`.
const SAFE_DOMINATORS: usize = 2;
const COST_SHIFT: u32 = 40;
const COST_LIMIT: i64 = 8191;
/// Slot levels per skill point are kept x12 (deco level / points: 1, 2, 3, 4, 4/3, 3/2...).
const UNIT: i64 = 12;
/// Weight of a point of a skill with no decoration in the aggregate bound (any positive value is valid).
const NO_DECO_UNIT: i64 = 4 * UNIT;

/// One candidate for one part (or a talisman).
#[derive(Clone, Debug, Default)]
pub struct Cand {
    /// Caller's id.
    pub key: u32,
    pub skills: Vec<(i32, i32)>,
    /// Slot levels, highest first.
    pub slots: [u8; 3],
    pub defense: i32,
    /// Generator the rolls come from (-1: nothing to roll) and the roll number in it (1-based).
    pub seq: i32,
    pub roll: u32,
    /// Stream of the sequence (see `Sync`; -1: the same for every piece).
    pub stream: i32,
}

impl Cand {
    fn cost(&self) -> u32 {
        if self.seq >= 0 {
            self.roll
        } else {
            0
        }
    }
}

#[derive(Clone, Debug)]
pub struct Deco {
    pub key: u32,
    pub skill: i32,
    /// Slot level it needs.
    pub level: u8,
    pub points: i32,
    /// How many can be used (`u32::MAX`: unlimited).
    pub count: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Value {
    /// Total defense of the five pieces.
    Defense,
    /// Preset score: weight x level (capped at the skill's max) of every skill, plus a value per free slot.
    Score,
}

/// Where each piece's stream of a sequence is: augments draw from the generator a different number
/// of times on different pieces (cost 10 armor), so after some rolls two pieces can be at different
/// places of the same sequence, and then one piece's roll is never reached after the other's.
#[derive(Clone, Debug, Default)]
pub struct Sync {
    /// Per stream: (from step, group). Two streams are at the same place after `k` augments when their
    /// groups at `k` are equal; groups only split, so equal at `k` means equal at every step before.
    pub lineage: HashMap<i32, Vec<(u32, i32)>>,
    /// Per sequence: the first step after which its streams are not all at the same place.
    pub split: HashMap<i32, u32>,
}

impl Sync {
    fn group(&self, stream: i32, step: u32) -> Option<i32> {
        let l = self.lineage.get(&stream)?;
        l.iter().take_while(|e| e.0 <= step).last().map(|e| e.1)
    }

    /// Rolls `a` and `b` (sequence, roll, stream) of two pieces can both be made.
    pub fn fits(&self, a: (i32, u32, i32), b: (i32, u32, i32)) -> bool {
        if a.0 != b.0 {
            return true;
        }
        if a.1 == b.1 {
            return false;
        }
        if a.2 == b.2 || a.2 < 0 || b.2 < 0 {
            return true;
        }
        let m = a.1.min(b.1);
        matches!((self.group(a.2, m), self.group(b.2, m)), (Some(x), Some(y)) if x == y)
    }

    /// Streams `a` and `b` are at the same place for the first `step` augments.
    fn together(&self, a: i32, b: i32, step: u32) -> bool {
        a == b || matches!((self.group(a, step), self.group(b, step)), (Some(x), Some(y)) if x == y)
    }

    /// Roll `r` of `seq` fits with every other roll of it but the same one, whatever the piece.
    fn universal(&self, seq: i32, r: u32) -> bool {
        self.split.get(&seq).is_none_or(|&s| r < s)
    }
}

#[derive(Clone, Debug)]
pub struct Query {
    pub parts: [Vec<Cand>; 5],
    pub talismans: Vec<Cand>,
    pub weapon: [u8; 3],
    pub decos: Vec<Deco>,
    /// Requested skills (skill, minimum level).
    pub reqs: Vec<(i32, i32)>,
    /// Max level per skill (1-based).
    pub max_levels: HashMap<i32, i32>,
    /// Score weight per skill level.
    pub weights: HashMap<i32, f64>,
    /// Value of a free slot by level (0..=4).
    pub slot_values: [f64; 5],
    pub value: Value,
    /// Fewest rolls first, then the best value; otherwise the best value, then the fewest rolls.
    pub cost_first: bool,
    pub max_cost: u32,
    pub limit: usize,
    /// Only sets worth at least this much (score x 1, defense x 1); 0 = any.
    pub floor: f64,
    pub sync: Sync,
    /// Rolls already paid for per sequence (default 0): a set costs, per sequence, only the rolls past
    /// this (another plan rolls that far anyway).
    pub base: HashMap<i32, u32>,
}

impl Query {
    fn base_of(&self, seq: i32) -> u32 {
        self.base.get(&seq).copied().unwrap_or(0)
    }

    /// The rolls a candidate costs on its own: its roll number past the sequence's base.
    fn roll_cost(&self, c: &Cand) -> u32 {
        if c.seq >= 0 {
            c.roll.saturating_sub(self.base_of(c.seq))
        } else {
            0
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct SetResult {
    /// Candidate keys of head..legs (`None`: nothing).
    pub parts: [Option<u32>; 5],
    pub talisman: Option<u32>,
    /// (owner: 0 weapon, 1..=5 head..legs, 6 talisman; slot index; decoration key; true = extra, not for a request)
    pub decos: Vec<(u8, u8, u32, bool)>,
    /// Every skill of the set, capped at its max level, highest first.
    pub skills: Vec<(i32, i32)>,
    /// Levels of the slots left empty, highest first.
    pub free_slots: Vec<u8>,
    pub cost: u32,
    pub defense: i32,
    pub score: f64,
}

#[derive(Clone)]
struct P {
    key: Option<u32>,
    pts: [i32; MAX_REQ],
    cap: [i32; 5],
    slots: [u8; 3],
    skills: Vec<(i32, i32)>,
    defense: i32,
    seq: i32,
    roll: u32,
    stream: i32,
    cost: u32,
    /// Upper bound of what it adds to the value.
    ub: i64,
    /// Requested skill points (capped at the request) plus slot levels, in slot-level units x12.
    offer: i64,
    /// Score mode: levels of weighted skills (index into `Ctx::wskills`) and the best value of its slots.
    wlv: Vec<(usize, i32)>,
    slot_ub: i64,
}

fn caps(slots: &[u8]) -> [i32; 5] {
    let mut out = [0; 5];
    for &s in slots {
        for c in out.iter_mut().take(s.min(4) as usize + 1).skip(1) {
            *c += 1;
        }
    }
    out
}

/// `dst[i] += src[i]`
fn add_into(dst: &mut [i32], src: &[i32]) {
    for (d, s) in dst.iter_mut().zip(src) {
        *d += s;
    }
}

fn level_of(skills: &[(i32, i32)], s: i32) -> i32 {
    skills
        .iter()
        .filter(|(x, _)| *x == s)
        .map(|(_, l)| *l)
        .sum()
}

struct Ctx<'a> {
    q: &'a Query,
    k: usize,
    req: Vec<i32>,
    /// Depth 0 = talismans, 1..=5 = head..legs.
    cands: Vec<Vec<P>>,
    suf_ub: [i64; DEPTH + 1],
    suf_pts: [[i32; MAX_REQ]; DEPTH + 1],
    suf_cap: [[i32; 5]; DEPTH + 1],
    weapon_cap: [i32; 5],
    weapon_ub: i64,
    /// Per requested skill: (deco index, level, points, count), lowest level first.
    deco_opts: Vec<Vec<(usize, u8, i32, u32)>>,
    deco_best: Vec<Option<(u8, i32)>>,
    /// Decorations worth placing in free slots (score mode): (deco index, weight per point x 100).
    extra_opts: Vec<(usize, i64)>,
    slot_val: [i64; 5],
    /// Slot levels (x12) a point of each requested skill takes as decorations.
    unit: Vec<i64>,
    suf_offer: [i64; DEPTH + 1],
    /// Score mode: weighted skills, their weight x100 and max level, and per depth the sum of the
    /// best level of each among the remaining candidates (for a bound that respects max levels).
    wskills: Vec<i32>,
    w100: Vec<i64>,
    wmax: Vec<i32>,
    suf_wlv: Vec<Vec<i32>>,
    suf_slot_ub: [i64; DEPTH + 1],
    /// Score mode: candidates of each depth by `ub`, highest first (for the room-aware bound).
    by_ub: Vec<Vec<usize>>,
    /// Candidates of each depth by `offer`, highest first (for the dynamic skill bound).
    by_offer: Vec<Vec<usize>>,
    floor: i64,
    best_slot: [i64; 5],
    widx: HashMap<i32, usize>,
    threshold: AtomicI64,
    deadline: Option<Instant>,
    nodes: AtomicU64,
    stopped: AtomicBool,
}

#[derive(Clone, PartialEq, Eq, PartialOrd, Ord)]
struct Found {
    obj: i64,
    free: i64,
    picks: [usize; DEPTH],
    decos: Vec<(usize, u32)>,
    /// Extra decorations: (deco index, slot level it takes).
    extras: Vec<(usize, u8)>,
}

impl<'a> Ctx<'a> {
    fn obj(&self, cost: u32, value: i64) -> i64 {
        if self.q.cost_first {
            value - ((cost as i64) << COST_SHIFT)
        } else {
            value * (COST_LIMIT + 1) - (cost as i64).min(COST_LIMIT)
        }
    }

    fn weight100(&self, s: i32) -> i64 {
        self.q
            .weights
            .get(&s)
            .map_or(0, |w| (w * 100.0).round() as i64)
    }

    fn max_level(&self, s: i32) -> i32 {
        self.q.max_levels.get(&s).copied().unwrap_or(7)
    }

    /// Best value a slot of each level can bring (score mode): empty, or the best decoration it fits.
    fn best_slot(q: &Query) -> [i64; 5] {
        let mut out = [0i64; 5];
        for (lv, o) in out.iter_mut().enumerate().skip(1) {
            let mut best = (q.slot_values[lv] * 100.0).round() as i64;
            for d in &q.decos {
                if d.level as usize <= lv && d.count > 0 {
                    let w = q.weights.get(&d.skill).copied().unwrap_or(0.0).max(0.0);
                    best = best.max((w * 100.0).round() as i64 * d.points as i64);
                }
            }
            *o = best;
        }
        out
    }

    fn prepare(
        q: &Query,
        c: &Cand,
        k: usize,
        best_slot: &[i64; 5],
        widx: &HashMap<i32, usize>,
    ) -> P {
        let mut pts = [0; MAX_REQ];
        for (i, (s, _)) in q.reqs.iter().take(k).enumerate() {
            pts[i] = level_of(&c.skills, *s);
        }
        let ub = match q.value {
            Value::Defense => c.defense as i64,
            Value::Score => {
                let sk: i64 = c
                    .skills
                    .iter()
                    .map(|(s, l)| {
                        (q.weights.get(s).copied().unwrap_or(0.0).max(0.0) * 100.0).round() as i64
                            * (*l).max(0) as i64
                    })
                    .sum();
                sk + c
                    .slots
                    .iter()
                    .map(|&s| best_slot[s.min(4) as usize])
                    .sum::<i64>()
            }
        };
        P {
            key: Some(c.key),
            pts,
            cap: caps(&c.slots),
            slots: c.slots,
            skills: c.skills.clone(),
            defense: c.defense,
            seq: c.seq,
            roll: c.roll,
            stream: c.stream,
            cost: q.roll_cost(c),
            ub,
            offer: 0,
            wlv: c
                .skills
                .iter()
                .filter_map(|(s, l)| Some((*widx.get(s)?, *l)))
                .filter(|e| e.1 > 0)
                .collect(),
            slot_ub: if q.value == Value::Score {
                c.slots.iter().map(|&s| best_slot[s.min(4) as usize]).sum()
            } else {
                0
            },
        }
    }

    fn empty(best_slot: &[i64; 5], value: Value) -> P {
        let _ = (best_slot, value);
        P {
            key: None,
            pts: [0; MAX_REQ],
            cap: [0; 5],
            slots: [0; 3],
            skills: vec![],
            defense: 0,
            seq: -1,
            roll: 0,
            stream: -1,
            cost: 0,
            ub: 0,
            offer: 0,
            wlv: vec![],
            slot_ub: 0,
        }
    }

    fn new(q: &'a Query) -> Self {
        let k = q.reqs.len().min(MAX_REQ);
        let best_slot = Self::best_slot(q);
        let cost_first = q.cost_first;
        let mut wskills: Vec<i32> = if q.value == Value::Score && !q.cost_first {
            q.weights
                .iter()
                .filter(|(_, w)| **w > 0.0)
                .map(|(s, _)| *s)
                .collect()
        } else {
            vec![]
        };
        wskills.sort_unstable();
        let widx: HashMap<i32, usize> = wskills.iter().enumerate().map(|(i, s)| (*s, i)).collect();
        let prune = |list: &[Cand]| -> Vec<P> {
            let mut ps: Vec<P> = list
                .iter()
                .filter(|c| q.roll_cost(c) <= q.max_cost)
                .map(|c| Self::prepare(q, c, k, &best_slot, &widx))
                .collect();
            ps.push(Self::empty(&best_slot, q.value));
            prune_dominated(ps, k, cost_first, &q.sync)
        };
        let mut deco_opts: Vec<Vec<(usize, u8, i32, u32)>> = vec![Vec::new(); k];
        for (j, d) in q.decos.iter().enumerate() {
            if d.count == 0 || d.points <= 0 {
                continue;
            }
            if let Some(i) = q.reqs.iter().take(k).position(|(r, _)| *r == d.skill) {
                deco_opts[i].push((j, d.level, d.points, d.count));
            }
        }
        for o in deco_opts.iter_mut() {
            o.sort_by_key(|x| (x.1, Reverse(x.2)));
        }
        let unit: Vec<i64> = deco_opts
            .iter()
            .map(|o| {
                o.iter()
                    .map(|x| x.1 as i64 * UNIT / x.2 as i64)
                    .min()
                    .unwrap_or(NO_DECO_UNIT)
                    .max(1)
            })
            .collect();
        let lists: Vec<&Vec<Cand>> = std::iter::once(&q.talismans)
            .chain(q.parts.iter())
            .collect();
        let mut cands: Vec<Vec<P>> = lists.par_iter().map(|l| prune(l)).collect();
        for list in cands.iter_mut() {
            for p in list.iter_mut() {
                p.offer = (0..k)
                    .map(|s| p.pts[s].clamp(0, q.reqs[s].1) as i64 * unit[s])
                    .sum::<i64>()
                    + UNIT * (1..=4).map(|l| p.cap[l] as i64).sum::<i64>();
            }
            if q.cost_first {
                list.sort_by_key(|p| (p.cost, Reverse(p.offer), Reverse(p.ub)));
            } else {
                list.sort_by_key(|p| (Reverse(p.ub), Reverse(p.offer), p.cost));
            }
        }

        let mut suf_ub = [0i64; DEPTH + 1];
        let mut suf_pts = [[0i32; MAX_REQ]; DEPTH + 1];
        let mut suf_cap = [[0i32; 5]; DEPTH + 1];
        let mut suf_offer = [0i64; DEPTH + 1];
        let w = wskills.len();
        let mut suf_wlv = vec![vec![0i32; w]; DEPTH + 1];
        let mut suf_slot_ub = [0i64; DEPTH + 1];
        for d in (0..DEPTH).rev() {
            suf_offer[d] = suf_offer[d + 1] + cands[d].iter().map(|p| p.offer).max().unwrap_or(0);
            suf_slot_ub[d] =
                suf_slot_ub[d + 1] + cands[d].iter().map(|p| p.slot_ub).max().unwrap_or(0);
            let mut best = vec![0i32; w];
            for p in &cands[d] {
                for &(i, l) in &p.wlv {
                    best[i] = best[i].max(l);
                }
            }
            for i in 0..w {
                suf_wlv[d][i] = suf_wlv[d + 1][i] + best[i];
            }
            suf_ub[d] = suf_ub[d + 1] + cands[d].iter().map(|p| p.ub).max().unwrap_or(0);
            let (next_pts, next_cap) = (suf_pts[d + 1], suf_cap[d + 1]);
            for (s, v) in suf_pts[d].iter_mut().enumerate().take(k) {
                *v = next_pts[s] + cands[d].iter().map(|p| p.pts[s]).max().unwrap_or(0);
            }
            for (l, v) in suf_cap[d].iter_mut().enumerate().skip(1) {
                *v = next_cap[l] + cands[d].iter().map(|p| p.cap[l]).max().unwrap_or(0);
            }
        }
        let deco_best = deco_opts
            .iter()
            .map(|o| Some((o.iter().map(|x| x.1).min()?, o.iter().map(|x| x.2).max()?)))
            .collect();
        let mut extra_opts: Vec<(usize, i64)> = Vec::new();
        if q.value == Value::Score {
            for (j, d) in q.decos.iter().enumerate() {
                let w = q.weights.get(&d.skill).copied().unwrap_or(0.0);
                if d.count > 0 && d.points > 0 && w > 0.0 {
                    extra_opts.push((j, (w * 100.0).round() as i64));
                }
            }
            extra_opts
                .sort_by_key(|&(j, w)| (Reverse(w * q.decos[j].points as i64), q.decos[j].level));
        }
        let weapon_cap = caps(&q.weapon);
        let weapon_ub = match q.value {
            Value::Defense => 0,
            Value::Score => q.weapon.iter().map(|&s| best_slot[s.min(4) as usize]).sum(),
        };
        let mut slot_val = [0i64; 5];
        for (l, v) in slot_val.iter_mut().enumerate() {
            *v = (q.slot_values[l] * 100.0).round() as i64;
        }
        let by_offer: Vec<Vec<usize>> = cands
            .iter()
            .map(|l| {
                let mut ix: Vec<usize> = (0..l.len()).collect();
                ix.sort_by_key(|&i| Reverse(l[i].offer));
                ix
            })
            .collect();
        let by_ub: Vec<Vec<usize>> = if w > 0 {
            cands
                .iter()
                .map(|l| {
                    let mut ix: Vec<usize> = (0..l.len()).collect();
                    ix.sort_by_key(|&i| Reverse(l[i].ub));
                    ix
                })
                .collect()
        } else {
            vec![]
        };
        Ctx {
            q,
            k,
            req: q.reqs.iter().take(k).map(|r| r.1).collect(),
            cands,
            suf_ub,
            suf_pts,
            suf_cap,
            weapon_cap,
            weapon_ub,
            deco_opts,
            deco_best,
            extra_opts,
            slot_val,
            unit,
            suf_offer,
            w100: wskills
                .iter()
                .map(|s| (q.weights[s] * 100.0).round() as i64)
                .collect(),
            wmax: wskills
                .iter()
                .map(|s| q.max_levels.get(s).copied().unwrap_or(7))
                .collect(),
            wskills,
            by_ub,
            by_offer,
            best_slot,
            widx,
            floor: match q.value {
                Value::Defense => q.floor.round() as i64,
                Value::Score => (q.floor * 100.0).round() as i64,
            },
            suf_wlv,
            suf_slot_ub,
            threshold: AtomicI64::new(i64::MIN),
            deadline: None,
            nodes: AtomicU64::new(0),
            stopped: AtomicBool::new(false),
        }
    }

    /// Score bound that respects max levels per candidate: what the set has now (capped) plus, for
    /// each remaining depth, the best candidate's levels up to each skill's remaining room
    /// (min(a + b, m) <= min(a, m) + min(b, m - a) makes the sum an upper bound).
    fn room_bound(&self, d: usize, wt: &[i32], slot_acc: i64) -> i64 {
        let now: i64 = (0..self.wskills.len())
            .map(|i| self.w100[i] * wt[i].min(self.wmax[i]).max(0) as i64)
            .sum::<i64>()
            + slot_acc;
        let mut rest = 0i64;
        for dd in d..DEPTH {
            let mut best = 0i64;
            for &c in &self.by_ub[dd] {
                let p = &self.cands[dd][c];
                if p.ub <= best {
                    break;
                }
                let gain: i64 = p
                    .wlv
                    .iter()
                    .map(|&(i, l)| self.w100[i] * l.min((self.wmax[i] - wt[i]).max(0)) as i64)
                    .sum::<i64>()
                    + p.slot_ub;
                best = best.max(gain);
            }
            rest += best;
        }
        now + rest
    }

    fn skill_bound_ok(&self, d: usize, pts: &[i32; MAX_REQ], cap: &[i32; 5]) -> bool {
        let mut need = [0i32; 5];
        for (s, &have) in pts.iter().enumerate().take(self.k) {
            let deficit = self.req[s] - have - self.suf_pts[d][s];
            if deficit <= 0 {
                continue;
            }
            let Some((lv, best)) = self.deco_best[s] else {
                return false;
            };
            let n = (deficit + best - 1) / best;
            for x in need.iter_mut().take(lv as usize + 1).skip(1) {
                *x += n;
            }
        }
        if !(1..=4).all(|l| need[l] <= cap[l] + self.suf_cap[d][l]) {
            return false;
        }
        // Aggregate: every missing point needs its slot levels, from slots or from points of the
        // remaining parts (a valid relaxation since a decoration of level L gives at most L / unit points).
        let missing: i64 = (0..self.k)
            .map(|s| (self.req[s] - pts[s]).max(0) as i64 * self.unit[s])
            .sum();
        let slots_now = UNIT * (1..=4).map(|l| cap[l] as i64).sum::<i64>();
        if missing > slots_now + self.suf_offer[d] {
            return false;
        }
        if missing == 0 || d == DEPTH {
            return true;
        }
        // The same with what is still missing: per remaining depth, the best candidate's points up
        // to each deficit plus its slots (min(a + b, m) <= min(a, m) + min(b, m) keeps it valid).
        let deficit: Vec<i64> = (0..self.k).map(|s| (self.req[s] - pts[s]).max(0) as i64).collect();
        let mut have = slots_now;
        for dd in d..DEPTH {
            let mut best = 0i64;
            for &c in &self.by_offer[dd] {
                let p = &self.cands[dd][c];
                if p.offer <= best {
                    break;
                }
                let gain = (0..self.k).map(|s| (p.pts[s] as i64).clamp(0, deficit[s]) * self.unit[s]).sum::<i64>()
                    + UNIT * (1..=4).map(|l| p.cap[l] as i64).sum::<i64>();
                best = best.max(gain);
            }
            have += best;
            if have >= missing {
                return true;
            }
        }
        false
    }

    /// Free slots (count per exact level) after placing `chosen`, largest decoration into the
    /// smallest slot that fits (optimal for nested slot levels).
    fn free_exact(&self, cap: &[i32; 5], chosen: &[(usize, u32)]) -> [i32; 5] {
        let mut exact = [0i32; 5];
        for l in 1..=4 {
            exact[l] = cap[l] - if l < 4 { cap[l + 1] } else { 0 };
        }
        let mut levels: Vec<u8> = chosen
            .iter()
            .flat_map(|&(j, n)| std::iter::repeat_n(self.q.decos[j].level, n as usize))
            .collect();
        levels.sort_unstable_by(|a, b| b.cmp(a));
        for lv in levels {
            if let Some(l) = (lv as usize..=4).find(|&l| exact[l] > 0) {
                exact[l] -= 1;
            }
        }
        exact
    }

    fn free_levels(exact: &[i32; 5]) -> i64 {
        (1..=4).map(|l| l as i64 * exact[l] as i64).sum()
    }

    fn place_decos(
        &self,
        pts: &[i32; MAX_REQ],
        cap: &[i32; 5],
    ) -> Option<(Vec<(usize, u32)>, i64)> {
        let deficits: Vec<i32> = (0..self.k).map(|s| (self.req[s] - pts[s]).max(0)).collect();
        if deficits.iter().all(|d| *d == 0) {
            return Some((vec![], Self::free_levels(&self.free_exact(cap, &[]))));
        }
        let mut best = None;
        let mut used = [0i32; 5];
        let mut chosen = Vec::new();
        self.deco_dfs(0, &deficits, cap, &mut used, &mut chosen, 0, &mut best);
        best
    }

    #[allow(clippy::too_many_arguments)]
    fn deco_dfs(
        &self,
        s: usize,
        deficits: &[i32],
        cap: &[i32; 5],
        used: &mut [i32; 5],
        chosen: &mut Vec<(usize, u32)>,
        cost: i32,
        best: &mut Option<(Vec<(usize, u32)>, i64)>,
    ) {
        let total: i64 = (1..=4).map(|l| cap[l] as i64).sum();
        if best.as_ref().is_some_and(|b| total - cost as i64 <= b.1) {
            return;
        }
        if s == self.k {
            let free = Self::free_levels(&self.free_exact(cap, chosen));
            if best.as_ref().is_none_or(|b| free > b.1) {
                *best = Some((chosen.clone(), free));
            }
            return;
        }
        if deficits[s] <= 0 {
            return self.deco_dfs(s + 1, deficits, cap, used, chosen, cost, best);
        }
        self.cover(s, 0, deficits[s], deficits, cap, used, chosen, cost, best);
    }

    #[allow(clippy::too_many_arguments)]
    fn cover(
        &self,
        s: usize,
        o: usize,
        left: i32,
        deficits: &[i32],
        cap: &[i32; 5],
        used: &mut [i32; 5],
        chosen: &mut Vec<(usize, u32)>,
        cost: i32,
        best: &mut Option<(Vec<(usize, u32)>, i64)>,
    ) {
        if left <= 0 {
            return self.deco_dfs(s + 1, deficits, cap, used, chosen, cost, best);
        }
        let opts = &self.deco_opts[s];
        if o == opts.len() {
            return;
        }
        let (j, lv, pt, count) = opts[o];
        let max_n = ((left + pt - 1) / pt).min(count.min(i32::MAX as u32) as i32);
        for n in (0..=max_n).rev() {
            if !(1..=lv as usize).all(|l| used[l] + n <= cap[l]) {
                continue;
            }
            for x in used.iter_mut().take(lv as usize + 1).skip(1) {
                *x += n;
            }
            if n > 0 {
                chosen.push((j, n as u32));
            }
            self.cover(
                s,
                o + 1,
                left - n * pt,
                deficits,
                cap,
                used,
                chosen,
                cost + n * lv as i32,
                best,
            );
            if n > 0 {
                chosen.pop();
            }
            for x in used.iter_mut().take(lv as usize + 1).skip(1) {
                *x -= n;
            }
        }
    }

    /// Score mode: the set's value with greedy extra decorations in the free slots.
    fn score_value(
        &self,
        picks: &[usize; DEPTH],
        decos: &[(usize, u32)],
        exact: &[i32; 5],
    ) -> (i64, Vec<(usize, u8)>) {
        let mut totals: Vec<(i32, i32)> = Vec::with_capacity(24);
        let mut add = |s: i32, l: i32| match totals.iter_mut().find(|(x, _)| *x == s) {
            Some(e) => e.1 += l,
            None => totals.push((s, l)),
        };
        for (d, &c) in picks.iter().enumerate() {
            for &(s, l) in &self.cands[d][c].skills {
                add(s, l);
            }
        }
        let mut left: HashMap<usize, u32> = HashMap::new();
        for &(j, n) in decos {
            add(self.q.decos[j].skill, self.q.decos[j].points * n as i32);
            *left.entry(j).or_insert(0) += n;
        }
        let mut free: Vec<u8> = Vec::new();
        for l in (1..=4).rev() {
            for _ in 0..exact[l] {
                free.push(l as u8);
            }
        }
        let mut extras = Vec::new();
        let mut value_slots = 0i64;
        for &lv in &free {
            let mut best: Option<(usize, i64)> = None;
            for &(j, w) in &self.extra_opts {
                let d = &self.q.decos[j];
                if d.level > lv || left.get(&j).copied().unwrap_or(0) >= d.count {
                    continue;
                }
                let cur = totals
                    .iter()
                    .find(|(x, _)| *x == d.skill)
                    .map_or(0, |e| e.1);
                let room = (self.max_level(d.skill) - cur).max(0).min(d.points);
                let gain = w * room as i64;
                if gain > best.map_or(0, |b| b.1) {
                    best = Some((j, gain));
                }
            }
            match best {
                Some((j, gain)) if gain > self.slot_val[lv as usize] => {
                    let d = &self.q.decos[j];
                    match totals.iter_mut().find(|(x, _)| *x == d.skill) {
                        Some(e) => e.1 += d.points,
                        None => totals.push((d.skill, d.points)),
                    }
                    *left.entry(j).or_insert(0) += 1;
                    extras.push((j, lv));
                }
                _ => value_slots += self.slot_val[lv as usize],
            }
        }
        let skills: i64 = totals
            .iter()
            .map(|&(s, l)| self.weight100(s) * l.clamp(0, self.max_level(s)) as i64)
            .sum();
        (skills + value_slots, extras)
    }

    #[allow(clippy::too_many_arguments)]
    fn dfs(
        &self,
        d: usize,
        picks: &mut [usize; DEPTH],
        rolls: &mut Vec<(i32, u32, i32)>,
        cost: u32,
        value: i64,
        pts: [i32; MAX_REQ],
        cap: [i32; 5],
        wt: &mut [i32],
        slot_acc: i64,
        heap: &mut BinaryHeap<Reverse<Found>>,
    ) {
        if cost > self.q.max_cost {
            return;
        }
        let mut bound = value + self.suf_ub[d];
        if !self.wskills.is_empty() {
            let capped: i64 = (0..self.wskills.len())
                .map(|i| {
                    self.w100[i] * (wt[i] + self.suf_wlv[d][i]).min(self.wmax[i]).max(0) as i64
                })
                .sum::<i64>()
                + slot_acc
                + self.suf_slot_ub[d];
            bound = bound.min(capped);
            if bound >= self.floor && d < DEPTH {
                bound = bound.min(self.room_bound(d, wt, slot_acc));
            }
        }
        if bound < self.floor || self.obj(cost, bound) < self.threshold.load(Ordering::Relaxed) {
            return;
        }
        if self.stopped.load(Ordering::Relaxed) {
            return;
        }
        let n = self.nodes.fetch_add(1, Ordering::Relaxed);
        if n.is_multiple_of(PROGRESS_EVERY) {
            PROGRESS_NODES.fetch_add(PROGRESS_EVERY, Ordering::Relaxed);
            if CANCEL.load(Ordering::Relaxed) {
                self.stopped.store(true, Ordering::Relaxed);
                return;
            }
        }
        if let Some(t) = self.deadline {
            if n.is_multiple_of(65536) && Instant::now() > t {
                self.stopped.store(true, Ordering::Relaxed);
                return;
            }
        }
        if !self.skill_bound_ok(d, &pts, &cap) {
            return;
        }
        if d == DEPTH {
            let Some((decos, mut free)) = self.place_decos(&pts, &cap) else {
                return;
            };
            let (value, extras) = match self.q.value {
                Value::Defense => (value, vec![]),
                Value::Score => {
                    let exact = self.free_exact(&cap, &decos);
                    let (v, extras) = self.score_value(picks, &decos, &exact);
                    free -= extras.iter().map(|e| e.1 as i64).sum::<i64>();
                    (v, extras)
                }
            };
            let obj = self.obj(cost, value);
            if value < self.floor || obj < self.threshold.load(Ordering::Relaxed) {
                return;
            }
            heap.push(Reverse(Found {
                obj,
                free,
                picks: *picks,
                decos,
                extras,
            }));
            if heap.len() > self.q.limit {
                heap.pop();
            }
            if heap.len() == self.q.limit {
                self.threshold
                    .fetch_max(heap.peek().unwrap().0.obj, Ordering::Relaxed);
            }
            return;
        }
        for (c, p) in self.cands[d].iter().enumerate() {
            let mut add_cost = 0;
            if p.seq >= 0 {
                let mut top = self.q.base_of(p.seq);
                let mut clash = false;
                for &r in rolls.iter() {
                    if r.0 == p.seq {
                        clash |= !self.q.sync.fits(r, (p.seq, p.roll, p.stream));
                        top = top.max(r.1);
                    }
                }
                if clash {
                    continue;
                }
                add_cost = p.roll.saturating_sub(top);
            }
            let mut p2 = pts;
            add_into(&mut p2[..self.k], &p.pts[..self.k]);
            let mut c2 = cap;
            add_into(&mut c2, &p.cap);
            picks[d] = c;
            if p.seq >= 0 {
                rolls.push((p.seq, p.roll, p.stream));
            }
            let v = match self.q.value {
                Value::Defense => value + p.defense as i64,
                Value::Score => value + p.ub,
            };
            for &(i, l) in &p.wlv {
                wt[i] += l;
            }
            self.dfs(
                d + 1,
                picks,
                rolls,
                cost + add_cost,
                v,
                p2,
                c2,
                wt,
                slot_acc + p.slot_ub,
                heap,
            );
            for &(i, l) in &p.wlv {
                wt[i] -= l;
            }
            if p.seq >= 0 {
                rolls.pop();
            }
        }
    }

    fn assemble(&self, f: &Found) -> SetResult {
        let pieces: Vec<&P> = (0..DEPTH).map(|d| &self.cands[d][f.picks[d]]).collect();
        // Slots (owner, index, level), smallest first; decorations largest first, each into the
        // smallest free slot that fits.
        let mut slots: Vec<(u8, u8, u8)> = Vec::new();
        for (i, &lv) in self.q.weapon.iter().enumerate() {
            if lv > 0 {
                slots.push((0, i as u8, lv));
            }
        }
        for (d, p) in pieces.iter().enumerate() {
            let owner = if d == 0 { 6 } else { d as u8 };
            for (i, &lv) in p.slots.iter().enumerate() {
                if lv > 0 {
                    slots.push((owner, i as u8, lv));
                }
            }
        }
        slots.sort_by_key(|s| (s.2, s.0, s.1));
        let mut used = vec![false; slots.len()];
        let mut req: Vec<usize> = f
            .decos
            .iter()
            .flat_map(|&(j, n)| std::iter::repeat_n(j, n as usize))
            .collect();
        req.sort_by_key(|&j| Reverse(self.q.decos[j].level));
        let mut placed = Vec::new();
        let mut totals: Vec<(i32, i32)> = Vec::new();
        let mut add = |s: i32, l: i32| match totals.iter_mut().find(|(x, _)| *x == s) {
            Some(e) => e.1 += l,
            None => totals.push((s, l)),
        };
        for j in req {
            let d = &self.q.decos[j];
            if let Some(k) = (0..slots.len()).find(|&k| !used[k] && slots[k].2 >= d.level) {
                used[k] = true;
                placed.push((slots[k].0, slots[k].1, d.key, false));
                add(d.skill, d.points);
            }
        }
        for &(j, lv) in &f.extras {
            let d = &self.q.decos[j];
            if let Some(k) = (0..slots.len()).find(|&k| !used[k] && slots[k].2 == lv) {
                used[k] = true;
                placed.push((slots[k].0, slots[k].1, d.key, true));
                add(d.skill, d.points);
            }
        }
        for p in &pieces {
            for &(s, l) in &p.skills {
                add(s, l);
            }
        }
        let mut skills: Vec<(i32, i32)> = totals
            .into_iter()
            .filter(|e| e.1 > 0)
            .map(|(s, l)| (s, l.min(self.max_level(s))))
            .collect();
        skills.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
        let mut free_slots: Vec<u8> = slots
            .iter()
            .zip(&used)
            .filter(|(_, u)| !**u)
            .map(|(s, _)| s.2)
            .collect();
        free_slots.sort_unstable_by(|a, b| b.cmp(a));
        let mut seq_top: HashMap<i32, u32> = HashMap::new();
        for p in &pieces {
            if p.seq >= 0 {
                let e = seq_top.entry(p.seq).or_insert(0);
                *e = (*e).max(p.roll);
            }
        }
        let score = skills
            .iter()
            .map(|&(s, l)| self.weight100(s) * l as i64)
            .sum::<i64>()
            + free_slots
                .iter()
                .map(|&l| self.slot_val[l as usize])
                .sum::<i64>();
        SetResult {
            parts: [1, 2, 3, 4, 5].map(|d| pieces[d].key),
            talisman: pieces[0].key,
            decos: placed,
            skills,
            free_slots,
            cost: seq_top.iter().map(|(sq, t)| t.saturating_sub(self.q.base_of(*sq))).sum(),
            defense: pieces.iter().map(|p| p.defense).sum(),
            score: score as f64 / 100.0,
        }
    }
}

/// Keep only candidates no other candidate beats: same or fewer rolls, at least every requested
/// skill level and slot capacity, and at least the value (with `cost_first`, fewer rolls is enough).
///
/// A rolled dominator can be unusable in a set (another part took the same roll of its sequence),
/// so a candidate goes only when a dominator needs no roll or when `DEPTH - 1` dominators with
/// different rolls exist (the other parts cannot block them all). A rolled dominator only counts
/// when no other piece's stream can block it either: it is on the candidate's sequence and its
/// stream is at the same place as the candidate's until its roll (whatever fits the candidate then
/// fits it), or its roll comes before the streams of its sequence split.
fn prune_dominated(mut ps: Vec<P>, k: usize, cost_first: bool, sync: &Sync) -> Vec<P> {
    ps.sort_by_key(|p| {
        (
            p.cost,
            Reverse(p.ub),
            Reverse(p.pts[..k].iter().sum::<i32>()),
        )
    });
    let wl = |p: &P, i: usize| p.wlv.iter().find(|e| e.0 == i).map_or(0, |e| e.1);
    let dominates = |a: &P, b: &P| {
        a.cost <= b.cost
            && (1..=4).all(|l| a.cap[l] >= b.cap[l])
            && (0..k).all(|s| a.pts[s] >= b.pts[s])
            && ((cost_first && a.cost < b.cost) || a.ub >= b.ub)
            && b.wlv.iter().all(|&(i, l)| wl(a, i) >= l)
    };
    let mut kept: Vec<P> = Vec::with_capacity(ps.len().min(4096));
    'next: for c in ps {
        let mut rolled: Vec<(i32, u32)> = Vec::new();
        for x in &kept {
            if !dominates(x, &c) {
                continue;
            }
            if x.seq < 0 {
                continue 'next;
            }
            if !(x.seq == c.seq && sync.together(x.stream, c.stream, x.roll)) && !sync.universal(x.seq, x.roll) {
                continue;
            }
            if !rolled.contains(&(x.seq, x.roll)) {
                rolled.push((x.seq, x.roll));
                if rolled.len() >= SAFE_DOMINATORS {
                    continue 'next;
                }
            }
        }
        if c.seq < 0 {
            kept.retain(|x| !dominates(&c, x));
        }
        kept.push(c);
    }
    kept
}

/// What a search found.
#[derive(Clone, Debug)]
pub struct Outcome {
    pub sets: Vec<SetResult>,
    /// False when the deadline stopped the search: the sets are the best found, not proven best (or
    /// none was found in time).
    pub complete: bool,
}

/// The best `q.limit` sets, best first (none when no set reaches every requested level), searching
/// until `deadline`. With `cost_first` the roll budget grows step by step (0, 1, 2, 3, 5, 8...) until
/// `q.limit` sets fit in it: sets that need few rolls are found and proven fast, without searching
/// every far roll first.
pub fn search(q: &Query, deadline: Option<Instant>) -> Outcome {
    if !q.cost_first {
        return run(q, deadline);
    }
    let reach: u64 = std::iter::once(&q.talismans)
        .chain(q.parts.iter())
        .map(|l| l.iter().map(|c| q.roll_cost(c) as u64).max().unwrap_or(0))
        .sum();
    let top = (q.max_cost as u64).min(reach) as u32;
    let mut budget = 0u32;
    let mut done: Vec<SetResult> = Vec::new();
    loop {
        let mut step = q.clone();
        step.max_cost = budget.min(top);
        PROGRESS_BUDGET.store(step.max_cost as u64, Ordering::Relaxed);
        let mut out = run(&step, deadline);
        if !out.complete {
            // the sets of the last finished budget are exact; add what this one found beyond them
            let prev = done.len();
            let have = |s: &SetResult| done.iter().any(|d| d.parts == s.parts && d.talisman == s.talisman);
            let extra: Vec<SetResult> = out.sets.into_iter().filter(|s| !have(s)).collect();
            done.extend(extra);
            done[prev..].sort_by_key(|s| s.cost);
            done.truncate(q.limit);
            out.sets = done;
            return out;
        }
        // `limit` sets within the budget are the best `limit` overall: any other needs more rolls
        if out.sets.len() >= q.limit || budget >= top {
            return out;
        }
        done = out.sets;
        // small steps: each costs several times the one before, so overshooting the rolls needed is expensive
        budget = if budget < 2 { budget + 1 } else { budget.saturating_add(budget.div_ceil(2)) };
    }
}

fn run(q: &Query, deadline: Option<Instant>) -> Outcome {
    let mut ctx = Ctx::new(q);
    ctx.deadline = deadline;
    let ctx = ctx;
    let mut jobs: Vec<(usize, usize)> = (0..ctx.cands[0].len())
        .flat_map(|t| (0..ctx.cands[1].len()).map(move |h| (t, h)))
        .collect();
    jobs.sort_by_key(|&(t, h)| ctx.cands[0][t].cost + ctx.cands[1][h].cost);
    let mut found: Vec<Found> = jobs
        .par_iter()
        .map(|&(t, h)| {
            let mut heap = BinaryHeap::new();
            let mut picks = [t, h, 0, 0, 0, 0];
            let mut rolls = Vec::with_capacity(DEPTH);
            let (tp, hp) = (&ctx.cands[0][t], &ctx.cands[1][h]);
            if tp.seq >= 0
                && hp.seq >= 0
                && !q.sync.fits((tp.seq, tp.roll, tp.stream), (hp.seq, hp.roll, hp.stream))
            {
                return vec![];
            }
            let mut pts = tp.pts;
            add_into(&mut pts[..ctx.k], &hp.pts[..ctx.k]);
            let mut cap = ctx.weapon_cap;
            add_into(&mut cap, &tp.cap);
            add_into(&mut cap, &hp.cap);
            let mut cost = 0;
            for p in [tp, hp] {
                if p.seq >= 0 {
                    let top = rolls
                        .iter()
                        .filter(|r: &&(i32, u32, i32)| r.0 == p.seq)
                        .map(|r| r.1)
                        .max()
                        .unwrap_or(0)
                        .max(q.base_of(p.seq));
                    cost += p.roll.saturating_sub(top);
                    rolls.push((p.seq, p.roll, p.stream));
                }
            }
            let value = match q.value {
                Value::Defense => (tp.defense + hp.defense) as i64,
                Value::Score => ctx.weapon_ub + tp.ub + hp.ub,
            };
            let mut wt = vec![0i32; ctx.wskills.len()];
            for &(i, l) in tp.wlv.iter().chain(&hp.wlv) {
                wt[i] += l;
            }
            let slot_acc = ctx.weapon_ub + tp.slot_ub + hp.slot_ub;
            ctx.dfs(
                2, &mut picks, &mut rolls, cost, value, pts, cap, &mut wt, slot_acc, &mut heap,
            );
            heap.into_vec().into_iter().map(|r| r.0).collect::<Vec<_>>()
        })
        .flatten()
        .collect();
    found.sort_by(|a, b| b.cmp(a));
    found.truncate(q.limit);
    Outcome {
        sets: found.iter().map(|f| ctx.assemble(f)).collect(),
        complete: !ctx.stopped.load(Ordering::Relaxed),
    }
}

// ---- local search (build optimizer) ---------------------------------------------------------------

#[derive(Clone)]
struct Sol {
    picks: [usize; DEPTH],
    cost: u32,
    value: i64,
    free: i64,
    decos: Vec<(usize, u32)>,
    extras: Vec<(usize, u8)>,
}

impl<'a> Ctx<'a> {
    /// A complete set: its rolls (None when two pieces' rolls of a sequence do not fit together or a
    /// request cannot be met), value and decorations.
    fn evaluate(&self, picks: &[usize; DEPTH]) -> Option<Sol> {
        let mut pts = [0i32; MAX_REQ];
        let mut cap = self.weapon_cap;
        let mut rolls: Vec<(i32, u32, i32)> = Vec::with_capacity(DEPTH);
        let mut defense = 0i64;
        for (d, &c) in picks.iter().enumerate() {
            let p = &self.cands[d][c];
            add_into(&mut pts[..self.k], &p.pts[..self.k]);
            add_into(&mut cap, &p.cap);
            if p.seq >= 0 {
                let r = (p.seq, p.roll, p.stream);
                if rolls.iter().any(|&x| !self.q.sync.fits(x, r)) {
                    return None;
                }
                rolls.push(r);
            }
            defense += p.defense as i64;
        }
        let mut top: Vec<(i32, u32)> = Vec::new();
        for &(sq, r, _) in &rolls {
            match top.iter_mut().find(|e| e.0 == sq) {
                Some(e) => e.1 = e.1.max(r),
                None => top.push((sq, r)),
            }
        }
        let cost: u32 = top.iter().map(|e| e.1.saturating_sub(self.q.base_of(e.0))).sum();
        if cost > self.q.max_cost {
            return None;
        }
        let (decos, mut free) = self.place_decos(&pts, &cap)?;
        let (value, extras) = match self.q.value {
            Value::Defense => (defense, vec![]),
            Value::Score => {
                let exact = self.free_exact(&cap, &decos);
                let (v, extras) = self.score_value(picks, &decos, &exact);
                free -= extras.iter().map(|e| e.1 as i64).sum::<i64>();
                (v, extras)
            }
        };
        Some(Sol {
            picks: *picks,
            cost,
            value,
            free,
            decos,
            extras,
        })
    }

    fn sol_found(&self, s: &Sol) -> Found {
        Found {
            obj: s.value,
            free: s.free,
            picks: s.picks,
            decos: s.decos.clone(),
            extras: s.extras.clone(),
        }
    }
}

/// Pareto front of (rolls, value): a set stays unless another needs no more rolls and is worth at least
/// as much (more, or as much with more free slot levels).
fn front_insert(front: &mut Vec<Sol>, s: Sol) -> bool {
    // more rolls must buy a higher value; at equal rolls and value, more free slot levels win
    let beats = |a: &Sol, b: &Sol| {
        a.cost <= b.cost
            && (a.value > b.value || (a.value == b.value && (a.cost < b.cost || a.free >= b.free)))
    };
    if front.iter().any(|f| beats(f, &s)) {
        return false;
    }
    front.retain(|f| !beats(&s, f));
    front.push(s);
    true
}

/// Best sets found by changing one or two parts (talisman included) at a time, starting from
/// `starts` (complete sets; a `None` part is empty) and from every set that improves on them, as a
/// Pareto front of rolls and value: the first set needs the fewest rolls, each next one needs more
/// and is worth more. Not exhaustive like `search`: a suggestion list for the build optimizer.
pub fn improve(q: &Query, starts: &[[Option<Cand>; DEPTH]], deadline: Option<Instant>) -> Outcome {
    let mut ctx = Ctx::new(q);
    ctx.deadline = deadline;
    // the start pieces are added unpruned
    let mut start_picks: Vec<[usize; DEPTH]> = Vec::new();
    for st in starts {
        let mut picks = [0usize; DEPTH];
        for d in 0..DEPTH {
            let p = match &st[d] {
                Some(c) => Ctx::prepare(q, c, ctx.k, &ctx.best_slot, &ctx.widx),
                None => Ctx::empty(&ctx.best_slot, q.value),
            };
            ctx.cands[d].push(p);
            picks[d] = ctx.cands[d].len() - 1;
        }
        start_picks.push(picks);
    }
    let ctx = ctx;
    let mut front: Vec<Sol> = Vec::new();
    let mut queue: Vec<Sol> = Vec::new();
    for picks in &start_picks {
        if let Some(s) = ctx.evaluate(picks) {
            if front_insert(&mut front, s.clone()) {
                queue.push(s);
            }
        }
    }
    let late = || deadline.is_some_and(|t| Instant::now() > t) || CANCEL.load(Ordering::Relaxed);
    const PAIR_TOP: usize = 40;
    let mut expanded = 0;
    while let Some(base) = queue.pop() {
        if late() || expanded >= 64 {
            ctx.stopped.store(late(), Ordering::Relaxed);
            break;
        }
        expanded += 1;
        // one part changed
        let singles: Vec<(usize, usize, Option<Sol>)> = (0..DEPTH)
            .flat_map(|d| (0..ctx.cands[d].len()).map(move |c| (d, c)))
            .collect::<Vec<_>>()
            .par_iter()
            .filter(|&&(d, c)| c != base.picks[d])
            .map(|&(d, c)| {
                let mut picks = base.picks;
                picks[d] = c;
                (d, c, ctx.evaluate(&picks))
            })
            .collect();
        let mut next: Vec<Sol> = Vec::new();
        for (_, _, s) in &singles {
            if let Some(s) = s {
                next.push(s.clone());
            }
        }
        // two parts changed: per part, the best single changes plus the candidates with the highest
        // value bound (pairs can meet a request that neither meets alone)
        let mut tops: Vec<Vec<usize>> = vec![Vec::new(); DEPTH];
        for (d, top) in tops.iter_mut().enumerate() {
            let mut by_value: Vec<(i64, usize)> = singles
                .iter()
                .filter(|e| e.0 == d)
                .filter_map(|e| e.2.as_ref().map(|s| (s.value, e.1)))
                .collect();
            by_value.sort_by_key(|e| Reverse(e.0));
            top.extend(by_value.iter().take(PAIR_TOP / 2).map(|e| e.1));
            let mut by_ub: Vec<usize> = (0..ctx.cands[d].len())
                .filter(|&c| c != base.picks[d])
                .collect();
            by_ub.sort_by_key(|&c| {
                (
                    Reverse(ctx.cands[d][c].ub + ctx.cands[d][c].offer),
                    ctx.cands[d][c].cost,
                )
            });
            for c in by_ub {
                if top.len() >= PAIR_TOP {
                    break;
                }
                if !top.contains(&c) {
                    top.push(c);
                }
            }
        }
        let pairs: Vec<Sol> = (0..DEPTH)
            .flat_map(|a| ((a + 1)..DEPTH).map(move |b| (a, b)))
            .flat_map(|(a, b)| {
                let (ta, tb) = (&tops[a], &tops[b]);
                ta.iter()
                    .flat_map(move |&x| tb.iter().map(move |&y| (a, x, b, y)))
            })
            .collect::<Vec<_>>()
            .par_iter()
            .filter_map(|&(a, x, b, y)| {
                let mut picks = base.picks;
                picks[a] = x;
                picks[b] = y;
                ctx.evaluate(&picks)
            })
            .collect();
        next.extend(pairs);
        next.sort_by_key(|s| (s.cost, Reverse(s.value), Reverse(s.free)));
        for s in next {
            if front_insert(&mut front, s.clone()) {
                queue.push(s);
            }
        }
        queue.retain(|s| front.iter().any(|f| f.picks == s.picks));
    }
    front.sort_by_key(|s| (s.cost, Reverse(s.value)));
    front.truncate(q.limit.max(1) * 4);
    Outcome {
        sets: front
            .iter()
            .map(|s| ctx.assemble(&ctx.sol_found(s)))
            .collect(),
        complete: !ctx.stopped.load(Ordering::Relaxed),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cand(key: u32, skills: &[(i32, i32)], slots: [u8; 3], defense: i32) -> Cand {
        Cand {
            key,
            skills: skills.to_vec(),
            slots,
            defense,
            seq: -1,
            roll: 0,
            stream: -1,
        }
    }

    fn query(parts: [Vec<Cand>; 5], reqs: &[(i32, i32)], decos: Vec<Deco>) -> Query {
        Query {
            parts,
            talismans: vec![],
            weapon: [0; 3],
            decos,
            reqs: reqs.to_vec(),
            max_levels: [(1, 7), (2, 3), (3, 3)].into_iter().collect(),
            weights: HashMap::new(),
            slot_values: [0.0; 5],
            value: Value::Defense,
            cost_first: true,
            max_cost: u32::MAX,
            limit: 5,
            floor: 0.0,
            sync: Sync::default(),
            base: HashMap::new(),
        }
    }

    fn deco(key: u32, skill: i32, level: u8, count: u32) -> Deco {
        Deco {
            key,
            skill,
            level,
            points: 1,
            count,
        }
    }

    #[test]
    fn decorations_fill_the_gap() {
        let parts = [
            vec![cand(1, &[(1, 2)], [1, 0, 0], 10)],
            vec![cand(2, &[(1, 2)], [2, 0, 0], 10)],
            vec![cand(3, &[], [0, 0, 0], 10)],
            vec![cand(4, &[], [0, 0, 0], 10)],
            vec![cand(5, &[], [0, 0, 0], 10)],
        ];
        let q = query(parts, &[(1, 6)], vec![deco(100, 1, 1, 9)]);
        let r = search(&q, None).sets;
        assert_eq!(r[0].parts, [Some(1), Some(2), Some(3), Some(4), Some(5)]);
        assert_eq!(r[0].decos.len(), 2);
        assert!(r[0].skills.contains(&(1, 6)));
        // owning only one decoration makes it impossible
        let q = query(q.parts.clone(), &[(1, 6)], vec![deco(100, 1, 1, 1)]);
        assert!(search(&q, None).sets.is_empty());
    }

    #[test]
    fn fewest_rolls_first_and_distinct_rolls_per_sequence() {
        let rolled = |key, roll| Cand {
            seq: 7,
            roll,
            ..cand(key, &[(2, 1)], [0, 0, 0], 1)
        };
        let parts = [
            vec![cand(1, &[], [0, 0, 0], 50), rolled(11, 3), rolled(12, 9)],
            vec![cand(2, &[], [0, 0, 0], 50), rolled(21, 3), rolled(22, 5)],
            vec![cand(3, &[], [0, 0, 0], 50)],
            vec![cand(4, &[], [0, 0, 0], 50)],
            vec![cand(5, &[], [0, 0, 0], 50)],
        ];
        let q = query(parts, &[(2, 2)], vec![]);
        let r = search(&q, None).sets;
        // roll 3 can only be used once: head roll 3 + chest roll 5 costs 5 rolls of sequence 7
        assert_eq!(r[0].parts[..2], [Some(11), Some(22)]);
        assert_eq!(r[0].cost, 5);
    }

    #[test]
    fn base_counts_only_the_rolls_past_it() {
        let rolled = |key, roll| Cand {
            seq: 7,
            roll,
            ..cand(key, &[(1, 3)], [0, 0, 0], 10)
        };
        // head roll 9 (3 points) or head roll 4 (3 points) on a sequence already rolled to 8
        let mut q = query(
            [vec![cand(1, &[], [0, 0, 0], 50), rolled(11, 9), rolled(12, 4)], vec![], vec![], vec![], vec![]],
            &[(1, 3)],
            vec![],
        );
        q.base = [(7, 8)].into_iter().collect();
        let r = search(&q, None).sets;
        assert_eq!(r[0].cost, 0);      // roll 4 is inside what is rolled anyway
        assert_eq!(r[0].parts[0], Some(12));
        q.base = [(7, 2)].into_iter().collect();
        assert_eq!(search(&q, None).sets[0].cost, 2);
    }

    #[test]
    fn rolls_of_split_streams_do_not_mix() {
        // two pieces of sequence 7: streams 100 and 200 are at the same place for 3 augments, then split
        let rolled = |key, roll, stream| Cand {
            seq: 7,
            roll,
            stream,
            ..cand(key, &[(2, 1)], [0, 0, 0], 1)
        };
        let parts = [
            vec![cand(1, &[], [0, 0, 0], 50), rolled(11, 4, 100), rolled(12, 9, 100)],
            vec![cand(2, &[], [0, 0, 0], 50), rolled(21, 5, 200), rolled(22, 2, 200)],
            vec![cand(3, &[], [0, 0, 0], 50)],
            vec![cand(4, &[], [0, 0, 0], 50)],
            vec![cand(5, &[], [0, 0, 0], 50)],
        ];
        let mut q = query(parts, &[(2, 2)], vec![]);
        q.sync.lineage = [(100, vec![(0, 7), (4, 100)]), (200, vec![(0, 7), (4, 200)])]
            .into_iter()
            .collect();
        q.sync.split = [(7, 4)].into_iter().collect();
        assert!(!q.sync.fits((7, 4, 100), (7, 5, 200)));
        assert!(q.sync.fits((7, 3, 100), (7, 5, 200)));
        let r = search(&q, None).sets;
        // head 4 + chest 5 split apart after roll 4; chest 2 then head 4 fits (same place after 2)
        assert_eq!(r[0].parts[..2], [Some(11), Some(22)]);
        assert_eq!(r[0].cost, 4);
        assert!(r.iter().all(|s| s.parts[..2] != [Some(11), Some(21)]));
        let start: [Option<Cand>; 6] = Default::default();
        let front = improve(&q, &[start], None).sets;
        assert!(front.iter().all(|s| s.parts[..2] != [Some(11), Some(21)]));
    }

    #[test]
    fn score_mode_prefers_weighted_skills() {
        let parts = [
            vec![
                cand(1, &[(2, 1)], [0, 0, 0], 99),
                cand(6, &[(3, 1)], [0, 0, 0], 1),
            ],
            vec![cand(2, &[], [0, 0, 0], 1)],
            vec![cand(3, &[], [0, 0, 0], 1)],
            vec![cand(4, &[], [0, 0, 0], 1)],
            vec![cand(5, &[], [0, 0, 0], 1)],
        ];
        let mut q = query(parts, &[], vec![]);
        q.value = Value::Score;
        q.cost_first = false;
        q.weights = [(3, 10.0), (2, 1.0)].into_iter().collect();
        let r = search(&q, None).sets;
        assert_eq!(r[0].parts[0], Some(6));
        assert_eq!(r[0].score, 10.0);
    }

    /// Tiny xorshift for random instances.
    struct R(u64);
    impl R {
        fn next(&mut self) -> u64 {
            self.0 ^= self.0 << 13;
            self.0 ^= self.0 >> 7;
            self.0 ^= self.0 << 17;
            self.0
        }
        fn below(&mut self, n: u64) -> u64 {
            self.next() % n
        }
    }

    /// Random small instance: 2 requested skills (one decoration each, 1 point), a few candidates per
    /// part, some of them rolled from two shared sequences.
    fn random_query(seed: u64) -> Query {
        let mut r = R(seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) | 1);
        let mut key = 0;
        let mut piece = |r: &mut R, rolled: bool| {
            key += 1;
            let mut skills = vec![];
            for s in 1..=2 {
                let l = r.below(3) as i32;
                if l > 0 {
                    skills.push((s, l));
                }
            }
            let mut slots = [r.below(5) as u8, r.below(4) as u8, r.below(3) as u8];
            slots.sort_unstable_by(|a, b| b.cmp(a));
            let (seq, roll) = if rolled {
                (r.below(2) as i32, 1 + r.below(6) as u32)
            } else {
                (-1, 0)
            };
            Cand {
                key,
                skills,
                slots,
                defense: 50 + r.below(50) as i32,
                seq,
                roll,
                stream: -1,
            }
        };
        let parts: [Vec<Cand>; 5] =
            std::array::from_fn(|_| (0..4).map(|i| piece(&mut r, i >= 2)).collect());
        let talismans = (0..3)
            .map(|i| Cand {
                defense: 0,
                ..piece(&mut r, i == 2)
            })
            .collect();
        Query {
            parts,
            talismans,
            weapon: [r.below(3) as u8, 0, 0],
            decos: vec![
                Deco {
                    key: 1,
                    skill: 1,
                    level: 1 + r.below(3) as u8,
                    points: 1,
                    count: u32::MAX,
                },
                Deco {
                    key: 2,
                    skill: 2,
                    level: 1 + r.below(4) as u8,
                    points: 1,
                    count: u32::MAX,
                },
            ],
            reqs: vec![(1, 4 + r.below(4) as i32), (2, 3 + r.below(4) as i32)],
            max_levels: [(1, 7), (2, 7)].into_iter().collect(),
            weights: HashMap::new(),
            slot_values: [0.0; 5],
            value: Value::Defense,
            cost_first: true,
            max_cost: u32::MAX,
            limit: 3,
            floor: 0.0,
            sync: Sync::default(),
            base: HashMap::new(),
        }
    }

    /// Every combination: fewest rolls, then most defense (None if no set reaches the requests).
    fn brute(q: &Query) -> Option<(u32, i32)> {
        let none = Cand {
            key: 0,
            skills: vec![],
            slots: [0; 3],
            defense: 0,
            seq: -1,
            roll: 0,
            stream: -1,
        };
        let lists: Vec<Vec<&Cand>> = std::iter::once(&q.talismans)
            .chain(q.parts.iter())
            .map(|l| l.iter().chain(std::iter::once(&none)).collect())
            .collect();
        let mut best: Option<(u32, i32)> = None;
        let mut idx = [0usize; 6];
        loop {
            let set: Vec<&Cand> = (0..6).map(|d| lists[d][idx[d]]).collect();
            let mut rolls: Vec<(i32, u32)> = vec![];
            let mut clash = false;
            for (i, c) in set.iter().enumerate() {
                if c.seq >= 0 {
                    clash |= set[..i].iter().any(|o| {
                        o.seq >= 0 && !q.sync.fits((o.seq, o.roll, o.stream), (c.seq, c.roll, c.stream))
                    });
                    rolls.push((c.seq, c.roll));
                }
            }
            if !clash {
                let cost: u32 = [0, 1]
                    .iter()
                    .map(|s| {
                        rolls
                            .iter()
                            .filter(|r| r.0 == *s)
                            .map(|r| r.1)
                            .max()
                            .unwrap_or(0)
                    })
                    .sum();
                // decorations: for each level L, the decorations needing >= L fit in the slots >= L
                let mut cap = caps(&q.weapon);
                for c in &set {
                    add_into(&mut cap, &caps(&c.slots));
                }
                let mut need = [0i32; 5];
                for (i, (s, req)) in q.reqs.iter().enumerate() {
                    let have: i32 = set.iter().map(|c| level_of(&c.skills, *s)).sum();
                    let lv = q.decos[i].level as usize;
                    for x in need.iter_mut().take(lv + 1).skip(1) {
                        *x += (req - have).max(0);
                    }
                }
                if (1..=4).all(|l| need[l] <= cap[l]) {
                    let def: i32 = set.iter().map(|c| c.defense).sum();
                    if best.is_none_or(|b| (cost, -def) < (b.0, -b.1)) {
                        best = Some((cost, def));
                    }
                }
            }
            let mut d = 0;
            while d < 6 {
                idx[d] += 1;
                if idx[d] < lists[d].len() {
                    break;
                }
                idx[d] = 0;
                d += 1;
            }
            if d == 6 {
                return best;
            }
        }
    }

    #[test]
    fn matches_brute_force_on_random_sets() {
        let mut found = 0;
        for seed in 1..=300 {
            let q = random_query(seed);
            let want = brute(&q);
            let got = search(&q, None);
            assert!(got.complete);
            let got = got.sets.first().map(|s| (s.cost, s.defense));
            assert_eq!(got, want, "seed {seed}");
            if let Some(s) = search(&q, None).sets.first() {
                for (sk, req) in &q.reqs {
                    assert!(
                        s.skills.iter().any(|(x, l)| x == sk && l >= req),
                        "seed {seed}: request not met"
                    );
                }
                found += 1;
            }
        }
        assert!(
            found > 50,
            "too few feasible instances ({found}) to mean anything"
        );
    }

    #[test]
    fn matches_brute_force_with_split_streams() {
        let mut found = 0;
        for seed in 1..=300 {
            let mut q = random_query(seed);
            let mut r = R(seed.wrapping_mul(0xD1B5_4A32_D192_ED03) | 1);
            // per sequence, streams 10*seq + 0..3 share a place until a random step, then split in two
            // groups (stream 3 splits from the others one step later)
            for seq in 0..2 {
                let at = 1 + r.below(5) as u32;
                q.sync.split.insert(seq, at);
                for st in 0..4 {
                    let id = 10 * seq + st;
                    let mut l = vec![(0, 100 + seq)];
                    if st % 2 == 1 {
                        l.push((at, 200 + id));
                    }
                    if st == 2 {
                        l.push((at + 1, 300 + id));
                    }
                    q.sync.lineage.insert(id, l);
                }
            }
            for c in q.parts.iter_mut().flatten().chain(q.talismans.iter_mut()) {
                if c.seq >= 0 {
                    c.stream = 10 * c.seq + r.below(4) as i32;
                }
            }
            let want = brute(&q);
            let got = search(&q, None);
            assert!(got.complete);
            assert_eq!(got.sets.first().map(|s| (s.cost, s.defense)), want, "seed {seed}");
            found += want.is_some() as u32;
        }
        assert!(found > 50, "too few feasible instances ({found})");
    }

    #[test]
    fn improve_front_grows() {
        for seed in 1..=60 {
            let mut q = random_query(seed);
            q.cost_first = false;
            q.reqs.iter_mut().for_each(|r| r.1 = 2);
            let start: [Option<Cand>; 6] = Default::default();
            let out = improve(&q, &[start], None);
            for w in out.sets.windows(2) {
                assert!(
                    w[0].cost < w[1].cost && w[0].defense < w[1].defense,
                    "seed {seed}"
                );
            }
        }
    }
}
