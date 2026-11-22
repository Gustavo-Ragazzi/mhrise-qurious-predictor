//! `qurious_predictor._native`: the augment simulation of qurious-core for Python.
//!
//! `Scan` runs a search on a thread pool and is polled by the app (like the old worker processes):
//! every stream (armor piece x augment option) replays its generator; streams advance in rounds of
//! `CHUNK` rolls so they all reach about the same depth and the closest matches come first.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use pyo3::prelude::*;
use qurious_core as core;
use rayon::prelude::*;

const CHUNK: u64 = 128;

type SummaryTuple = (i32, i32, [i32; 5], Vec<(i32, i32)>);
type FilterArgs = (Vec<Vec<(i32, i32)>>, [i32; 3], Option<i32>, bool, bool, bool);
type PresetArgs = (Vec<(i32, f64)>, [f64; 4], f64);
/// (table, cost, armor skills, slot counts per level, augment type, generator state)
type StreamArgs = (i32, i32, Vec<(i32, i32)>, Vec<i32>, i32, [u32; 4]);
type EventTuple = (usize, u64, i32, i32, [i32; 5], Vec<(i32, i32)>, Option<(f64, f64)>);

fn tuple(s: core::Summary) -> SummaryTuple {
    (s.defense, s.slots, s.resistances, s.skills)
}

/// The qurious tables, built once and shared by every call.
#[pyclass(frozen)]
struct Tables(Arc<core::Tables>);

#[pymethods]
impl Tables {
    /// base = [(table, id, category, cost, values, lots)], armor_lots = [(table, category, id, lot)],
    /// category_lots = {table: [weights]}, skill_costs = [(skill, cost)], max_levels = {skill: 0-based max}.
    #[new]
    fn new(
        base: Vec<(i32, i32, i32, i32, Vec<i32>, Vec<u32>)>,
        armor_lots: Vec<(i32, i32, i32, u32)>,
        category_lots: HashMap<i32, Vec<u32>>,
        skill_costs: Vec<(i32, i32)>,
        max_levels: HashMap<i32, i32>,
    ) -> Self {
        let base = base
            .into_iter()
            .map(|(table, id, category, cost, values, lots)| core::Buildup { table, id, category, cost, values, lots })
            .collect();
        Tables(Arc::new(core::Tables::new(base, armor_lots, category_lots, skill_costs, max_levels)))
    }
}

/// One augment: (entries as (category, id, value, skill, cost), generator state afterwards).
#[pyfunction]
fn create_result(
    tables: &Tables,
    state: [u32; 4],
    table: i32,
    cost: i32,
    skills: Vec<(i32, i32)>,
    buildup_type: i32,
) -> (Vec<(i32, i32, i32, i32, i32)>, [u32; 4]) {
    let mut rng = core::Rng::new(state);
    let mut res = Vec::with_capacity(8);
    core::create_result(&mut rng, &tables.0, table, cost, &skills, buildup_type, &mut res);
    (res.iter().map(|e| (e.category, e.id, e.value, e.skill, e.cost)).collect(), rng.state())
}

/// The next `count` augments of one piece and option, summarized.
#[pyfunction]
fn rolls(
    py: Python<'_>,
    tables: &Tables,
    state: [u32; 4],
    table: i32,
    cost: i32,
    skills: Vec<(i32, i32)>,
    buildup_type: i32,
    count: usize,
) -> Vec<SummaryTuple> {
    let t = tables.0.clone();
    py.allow_threads(move || {
        let mut rng = core::Rng::new(state);
        let mut res = Vec::with_capacity(8);
        (0..count)
            .map(|_| {
                core::create_result(&mut rng, &t, table, cost, &skills, buildup_type, &mut res);
                tuple(core::summarize(&res))
            })
            .collect()
    })
}

struct Shared {
    events: Mutex<Vec<EventTuple>>,
    scanned: Vec<AtomicU64>,
    ended: Vec<AtomicBool>,
    done: AtomicBool,
    cancel: AtomicBool,
}

struct Stream {
    idx: usize,
    table: i32,
    cost: i32,
    skills: Vec<(i32, i32)>,
    buildup_type: i32,
    rng: core::Rng,
    n: u64,
    found: u64,
    finished: bool,
    matcher: Option<core::Matcher>,
    scorer: Option<core::Scorer>,
    best: f64,
    buf: Vec<core::Entry>,
}

/// A running search. Filter mode reports every roll that passes the filter (up to `max_matches` per
/// stream); rank mode reports each stream's best-scoring roll whenever it improves, among the rolls
/// that pass the filter when one is given.
#[pyclass(frozen)]
struct Scan(Arc<Shared>);

#[pymethods]
impl Scan {
    #[new]
    #[pyo3(signature = (tables, streams, filter=None, preset=None, max_matches=50, limit=5_000_000, threads=0))]
    fn new(
        tables: &Tables,
        streams: Vec<StreamArgs>,
        filter: Option<FilterArgs>,
        preset: Option<PresetArgs>,
        max_matches: u64,
        limit: u64,
        threads: usize,
    ) -> PyResult<Self> {
        let t = tables.0.clone();
        let shared = Arc::new(Shared {
            events: Mutex::new(Vec::new()),
            scanned: streams.iter().map(|_| AtomicU64::new(0)).collect(),
            ended: streams.iter().map(|_| AtomicBool::new(false)).collect(),
            done: AtomicBool::new(false),
            cancel: AtomicBool::new(false),
        });
        let filter = filter.map(|(groups, min_slots, min_def, no_skill_loss, no_negative_res, gain_only)| core::Filter {
            groups,
            min_slots,
            min_def,
            no_skill_loss,
            no_negative_res,
            gain_only,
        });
        let preset = preset.map(|(weights, slot_steps, defense)| core::Preset { weights, slot_steps, defense });
        let mut states: Vec<Stream> = streams
            .into_iter()
            .enumerate()
            .map(|(idx, (table, cost, skills, slot_nums, buildup_type, state))| Stream {
                idx,
                table,
                cost,
                buildup_type,
                rng: core::Rng::new(state),
                n: 0,
                found: 0,
                finished: false,
                // Filter mode always matches; rank mode only scores the rolls that pass the filter, if any.
                matcher: if preset.is_none() || filter.is_some() {
                    Some(core::Matcher::new(&skills, &slot_nums, filter.clone().unwrap_or_default()))
                } else {
                    None
                },
                scorer: preset.as_ref().map(|p| core::Scorer::new(&skills, &slot_nums, p, &t.max_levels)),
                skills,
                best: f64::NEG_INFINITY,
                buf: Vec::with_capacity(8),
            })
            .collect();
        let threads = if threads > 0 {
            threads
        } else {
            std::thread::available_parallelism().map(|n| n.get()).unwrap_or(2).saturating_sub(1).max(1)
        };
        let pool = rayon::ThreadPoolBuilder::new()
            .num_threads(threads)
            .build()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        let sh = shared.clone();
        std::thread::spawn(move || {
            pool.install(|| {
                while !sh.cancel.load(Ordering::Relaxed) && states.iter().any(|s| !s.finished) {
                    states.par_iter_mut().filter(|s| !s.finished).for_each(|st| {
                        if sh.cancel.load(Ordering::Relaxed) {
                            return;
                        }
                        let mut local: Vec<EventTuple> = Vec::new();
                        for _ in 0..CHUNK {
                            st.n += 1;
                            core::create_result(&mut st.rng, &t, st.table, st.cost, &st.skills, st.buildup_type, &mut st.buf);
                            let s = core::summarize(&st.buf);
                            if let Some(sc) = &st.scorer {
                                if st.matcher.as_ref().is_some_and(|m| !m.matches(&s)) {
                                    if st.n >= limit {
                                        st.finished = true;
                                        break;
                                    }
                                    continue;
                                }
                                let (score, gain) = sc.score(&s);
                                if score > st.best {
                                    st.best = score;
                                    local.push((st.idx, st.n, s.defense, s.slots, s.resistances, s.skills, Some((score, gain))));
                                }
                            } else if st.matcher.as_ref().is_some_and(|m| m.matches(&s)) {
                                st.found += 1;
                                local.push((st.idx, st.n, s.defense, s.slots, s.resistances, s.skills, None));
                            }
                            if (st.scorer.is_none() && st.found >= max_matches) || st.n >= limit {
                                st.finished = true;
                                break;
                            }
                        }
                        if !local.is_empty() {
                            sh.events.lock().unwrap().extend(local);
                        }
                        sh.scanned[st.idx].store(st.n, Ordering::Relaxed);
                        if st.finished {
                            sh.ended[st.idx].store(true, Ordering::Relaxed);
                        }
                    });
                }
            });
            for e in &sh.ended {
                e.store(true, Ordering::Relaxed);
            }
            sh.done.store(true, Ordering::Release);
        });
        Ok(Scan(shared))
    }

    /// (events since `since`, rolls scanned per stream, stream ended flags, search finished)
    fn poll(&self, since: usize) -> (Vec<EventTuple>, Vec<u64>, Vec<bool>, bool) {
        let done = self.0.done.load(Ordering::Acquire);
        let events = self.0.events.lock().unwrap();
        (
            events.get(since..).map(|e| e.to_vec()).unwrap_or_default(),
            self.0.scanned.iter().map(|a| a.load(Ordering::Relaxed)).collect(),
            self.0.ended.iter().map(|a| a.load(Ordering::Relaxed)).collect(),
            done,
        )
    }

    fn cancel(&self) {
        self.0.cancel.store(true, Ordering::Relaxed);
    }

    #[getter]
    fn done(&self) -> bool {
        self.0.done.load(Ordering::Acquire)
    }
}

// ---- talisman melding ---------------------------------------------------------------------------------

use core::melding as meld;

/// (skills as (id, level), slot levels, missed, unsure, best (skill 1 level, skill 2 level, slot levels))
type TalTuple = (Vec<(i32, i32)>, [i32; 3], bool, bool, [i32; 3]);
type MeldRow = (i32, i32, i32, u32, Vec<u32>, Vec<u32>, Vec<u32>, Vec<u32>);
type GradeLists = (Vec<u32>, Vec<u32>, Vec<u32>);
/// (scanned, matches, first match, [(n, talisman, score, perfection, rank)])
type MeldScanTuple = (u64, u64, Option<u64>, Vec<(u64, TalTuple, f64, f64, u64)>);

fn tal_tuple(t: &meld::Talisman) -> TalTuple {
    (t.skills.clone(), t.slots, t.missed, t.unsure, t.best)
}

/// The melding tables (gamedata["melding"]), built once.
#[pyclass(frozen)]
struct MeldTables(Arc<meld::MeldTables>);

#[pymethods]
impl MeldTables {
    /// skills = [(method, skill, grade, pick rate, grade pick rates, skill 1 rates, miss rates, skill 2 rates)],
    /// grades = {method: (p1, p, p2)}, second = {grade: [chance per method]},
    /// slots = [[(grade 1, grade 2, [8 tables])] per slot], mystery = [(pick rate, slot levels)].
    #[new]
    fn new(
        skills: Vec<MeldRow>,
        grades: HashMap<i32, GradeLists>,
        second: HashMap<i32, Vec<u32>>,
        slots: Vec<Vec<meld::SlotParams>>,
        mystery: Vec<(u32, Vec<i32>)>,
    ) -> Self {
        let mut rows: HashMap<i32, Vec<meld::Row>> = meld::ORDER.iter().map(|&m| (m, Vec::new())).collect();
        for (m, skill, grade, pick_rate, gp, skill1, miss, skill2) in skills {
            if skill == 0 {
                continue;
            }
            if let Some(v) = rows.get_mut(&m) {
                let grade_pick = [gp.first().copied().unwrap_or(0), gp.get(1).copied().unwrap_or(0)];
                v.push(meld::Row { skill, grade, pick_rate, grade_pick, skill1, miss, skill2 });
            }
        }
        let grades = grades.into_iter().map(|(k, (a, b, c))| (k, [a, b, c])).collect();
        MeldTables(Arc::new(meld::MeldTables { rows, grades, second, slots, mystery }))
    }
}

fn melder<'a>(t: &'a meld::MeldTables, method: i32, target: Option<i32>, previous: (Option<i32>, Option<i32>)) -> PyResult<meld::Melder<'a>> {
    meld::Melder::new(t, method, target, [previous.0, previous.1]).map_err(pyo3::exceptions::PyValueError::new_err)
}

/// The next `count` talismans of a method from a generator state (tests compare them with Python).
#[pyfunction]
#[pyo3(signature = (tables, method, target, state, count, previous=(None, None)))]
fn meld_rolls(
    tables: &MeldTables,
    method: i32,
    target: Option<i32>,
    state: [u32; 4],
    count: usize,
    previous: (Option<i32>, Option<i32>),
) -> PyResult<Vec<TalTuple>> {
    let mut m = melder(&tables.0, method, target, previous)?;
    let mut rng = core::Rng::new(state);
    Ok((0..count).map(|_| tal_tuple(&m.talisman(&mut rng))).collect())
}

/// Simulates `count` talismans, filters (wanted = [(skill, min level)], min_slots), scores (weights per
/// skill level, slot values by level 0-4, max levels) and returns (scanned, matches, first match,
/// rows) with the `limit` best matches for `sort` ("n", "rank", "score", "perfection") and `dir`
/// (1 ascending, -1 descending): rows = [(n, talisman, score, perfection, rank)].
#[pyfunction]
#[pyo3(signature = (tables, method, target, state, count, wanted, min_slots, weights, slot_values, max_levels, sort, dir, limit))]
#[allow(clippy::too_many_arguments)]
fn meld_scan(
    py: Python<'_>,
    tables: &MeldTables,
    method: i32,
    target: Option<i32>,
    state: [u32; 4],
    count: u64,
    wanted: Vec<(i32, i32)>,
    min_slots: [i32; 3],
    weights: Vec<(i32, f64)>,
    slot_values: [f64; 5],
    max_levels: HashMap<i32, i32>,
    sort: &str,
    dir: i32,
    limit: usize,
) -> PyResult<MeldScanTuple> {
    let sort = match sort {
        "n" => meld::SortKey::N,
        "rank" => meld::SortKey::Rank,
        "score" => meld::SortKey::Score,
        "perfection" => meld::SortKey::Perfection,
        other => return Err(pyo3::exceptions::PyValueError::new_err(format!("unknown sort {other}"))),
    };
    let tables = tables.0.clone();
    let filter = meld::Filter { skills: wanted, slots: min_slots };
    let scorer = meld::Scorer::new(&weights, &max_levels, slot_values);
    let r = py.allow_threads(move || -> Result<meld::ScanResult, String> {
        let mut m = meld::Melder::new(&tables, method, target, [None, None])?;
        let mut rng = core::Rng::new(state);
        Ok(meld::scan(&mut m, &mut rng, count, &filter, &scorer, sort, dir, limit, &|| false))
    })
    .map_err(pyo3::exceptions::PyValueError::new_err)?;
    let rows = r
        .rows
        .iter()
        .map(|f| (f.n, tal_tuple(&f.talisman), f.score as f64 / 100.0, f.perfection, f.rank))
        .collect();
    Ok((r.scanned, r.matches, r.first_match, rows))
}

// ---- set builder ----------------------------------------------------------------------------------------

use core::sets;

/// (key, skills, slot levels, defense, sequence, roll)
type CandTuple = (u32, Vec<(i32, i32)>, [u8; 3], i32, i32, u32, i32);
/// (per stream: [(from step, group)], per sequence: first step its streams split); see `sets::Sync`
type SyncArgs = (HashMap<i32, Vec<(u32, i32)>>, HashMap<i32, u32>);
/// (key, skill, slot level, points, count)
type DecoTuple = (u32, i32, u8, i32, u32);
/// (parts, talisman, decos (owner, slot, deco key, extra), skills, free slots, cost, defense, score)
type SetTuple = (
    [Option<u32>; 5],
    Option<u32>,
    Vec<(u8, u8, u32, bool)>,
    Vec<(i32, i32)>,
    Vec<u8>,
    u32,
    i32,
    f64,
);

fn cand(t: CandTuple) -> sets::Cand {
    sets::Cand {
        key: t.0,
        skills: t.1,
        slots: t.2,
        defense: t.3,
        seq: t.4,
        roll: t.5,
        stream: t.6,
    }
}

#[allow(clippy::too_many_arguments)]
fn query_of(
    parts: [Vec<CandTuple>; 5],
    talismans: Vec<CandTuple>,
    weapon: [u8; 3],
    decos: Vec<DecoTuple>,
    reqs: Vec<(i32, i32)>,
    max_levels: HashMap<i32, i32>,
    weights: HashMap<i32, f64>,
    slot_values: [f64; 5],
    value: &str,
    cost_first: bool,
    max_cost: u32,
    limit: usize,
    floor: f64,
    sync: Option<SyncArgs>,
    base: Option<HashMap<i32, u32>>,
) -> PyResult<sets::Query> {
    let value = match value {
        "defense" => sets::Value::Defense,
        "score" => sets::Value::Score,
        other => {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "unknown value {other}"
            )))
        }
    };
    if reqs.len() > sets::MAX_REQ {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "at most {} skills",
            sets::MAX_REQ
        )));
    }
    Ok(sets::Query {
        parts: parts.map(|p| p.into_iter().map(cand).collect()),
        talismans: talismans.into_iter().map(cand).collect(),
        weapon,
        decos: decos
            .into_iter()
            .map(|(key, skill, level, points, count)| sets::Deco {
                key,
                skill,
                level,
                points,
                count,
            })
            .collect(),
        reqs,
        max_levels,
        weights,
        slot_values,
        value,
        cost_first,
        max_cost,
        limit: limit.max(1),
        floor,
        sync: sync
            .map(|(lineage, split)| sets::Sync { lineage, split })
            .unwrap_or_default(),
        base: base.unwrap_or_default(),
    })
}

fn deadline(seconds: f64) -> Option<std::time::Instant> {
    (seconds > 0.0).then(|| std::time::Instant::now() + std::time::Duration::from_secs_f64(seconds))
}

fn set_rows(out: sets::Outcome) -> (Vec<SetTuple>, bool) {
    let rows = out
        .sets
        .into_iter()
        .map(|r| {
            (
                r.parts,
                r.talisman,
                r.decos,
                r.skills,
                r.free_slots,
                r.cost,
                r.defense,
                r.score,
            )
        })
        .collect();
    (rows, out.complete)
}

/// The best sets (see `qurious_core::sets::search`) and whether the search finished within `seconds`.
/// `value` is "defense" or "score".
#[pyfunction]
#[pyo3(signature = (parts, talismans, weapon, decos, reqs, max_levels, weights, slot_values, value, cost_first, max_cost, limit, seconds=20.0, floor=0.0, sync=None, base=None))]
#[allow(clippy::too_many_arguments)]
fn set_search(
    py: Python<'_>,
    parts: [Vec<CandTuple>; 5],
    talismans: Vec<CandTuple>,
    weapon: [u8; 3],
    decos: Vec<DecoTuple>,
    reqs: Vec<(i32, i32)>,
    max_levels: HashMap<i32, i32>,
    weights: HashMap<i32, f64>,
    slot_values: [f64; 5],
    value: &str,
    cost_first: bool,
    max_cost: u32,
    limit: usize,
    seconds: f64,
    floor: f64,
    sync: Option<SyncArgs>,
    base: Option<HashMap<i32, u32>>,
) -> PyResult<(Vec<SetTuple>, bool)> {
    let q = query_of(
        parts,
        talismans,
        weapon,
        decos,
        reqs,
        max_levels,
        weights,
        slot_values,
        value,
        cost_first,
        max_cost,
        limit,
        floor,
        sync,
        base,
    )?;
    let t = deadline(seconds);
    Ok(set_rows(py.allow_threads(move || sets::search(&q, t))))
}

/// Pareto front of rolls and value from local changes of `starts` (see `qurious_core::sets::improve`).
/// starts = [[talisman, head, chest, arms, waist, legs]] as candidate tuples (None = nothing).
#[pyfunction]
#[pyo3(signature = (parts, talismans, weapon, decos, reqs, max_levels, weights, slot_values, value, max_cost, limit, starts, seconds=10.0, sync=None, base=None))]
#[allow(clippy::too_many_arguments)]
fn set_improve(
    py: Python<'_>,
    parts: [Vec<CandTuple>; 5],
    talismans: Vec<CandTuple>,
    weapon: [u8; 3],
    decos: Vec<DecoTuple>,
    reqs: Vec<(i32, i32)>,
    max_levels: HashMap<i32, i32>,
    weights: HashMap<i32, f64>,
    slot_values: [f64; 5],
    value: &str,
    max_cost: u32,
    limit: usize,
    starts: Vec<[Option<CandTuple>; 6]>,
    seconds: f64,
    sync: Option<SyncArgs>,
    base: Option<HashMap<i32, u32>>,
) -> PyResult<(Vec<SetTuple>, bool)> {
    let q = query_of(
        parts,
        talismans,
        weapon,
        decos,
        reqs,
        max_levels,
        weights,
        slot_values,
        value,
        false,
        max_cost,
        limit,
        0.0,
        sync,
        base,
    )?;
    let starts: Vec<[Option<sets::Cand>; 6]> = starts
        .into_iter()
        .map(|st| st.map(|c| c.map(cand)))
        .collect();
    let t = deadline(seconds);
    Ok(set_rows(
        py.allow_threads(move || sets::improve(&q, &starts, t)),
    ))
}

/// Results of one piece (or one talisman method) kept so far, earliest roll first: a later roll is
/// only worth keeping if no earlier one has at least its requested levels, slot capacity and score.
#[derive(Default)]
struct Frontier(Vec<(Vec<i32>, [i32; 5], f64)>);

impl Frontier {
    fn admit(&mut self, lv: Vec<i32>, caps: [i32; 5], value: f64) -> bool {
        let covered = self.0.iter().any(|(l, c, v)| {
            *v >= value && l.iter().zip(&lv).all(|(a, b)| a >= b) && c.iter().zip(&caps).all(|(a, b)| a >= b)
        });
        if !covered {
            self.0.push((lv, caps, value));
        }
        !covered
    }
}

fn slot_caps(slots: &[i32]) -> [i32; 5] {
    let mut out = [0; 5];
    for &s in slots {
        for c in out.iter_mut().take(s.clamp(0, 4) as usize + 1).skip(1) {
            *c += 1;
        }
    }
    out
}

/// Score of a piece's skills (uncapped) and slots; 0 without weights.
fn ub(
    weights: &HashMap<i32, f64>,
    slot_values: &[f64; 5],
    skills: &[(i32, i32)],
    slots: &[i32],
) -> f64 {
    if weights.is_empty() {
        return 0.0;
    }
    skills
        .iter()
        .map(|(s, l)| weights.get(s).copied().unwrap_or(0.0).max(0.0) * (*l).max(0) as f64)
        .sum::<f64>()
        + slots
            .iter()
            .map(|&l| slot_values[l.clamp(0, 4) as usize])
            .sum::<f64>()
}

/// (key, augment type, roll, skills, slot levels, defense change, resistance changes, skill changes, slot
/// points, stream)
type AugTuple = (u32, i32, u32, Vec<(i32, i32)>, [u8; 3], i32, [i32; 5], Vec<(i32, i32)>, i32, i32);
/// (key, table, cost, skills, slot counts per level)
type PieceArgs = (u32, i32, i32, Vec<(i32, i32)>, Vec<i32>);

/// Augments every stream makes per round of `augment_candidates` before the streams are compared.
const AUG_ROUND: u32 = 512;

/// Rolls simulated so far by `augment_candidates` (progress for the app).
static PROGRESS_ROLLS: AtomicU64 = AtomicU64::new(0);

/// Stop the running set search / candidate simulation (they return what they have).
#[pyfunction]
fn search_cancel() {
    sets::CANCEL.store(true, Ordering::Relaxed);
}

/// Before a new search: clear the stop flag and the progress counters.
#[pyfunction]
fn search_reset() {
    sets::CANCEL.store(false, Ordering::Relaxed);
    sets::PROGRESS_NODES.store(0, Ordering::Relaxed);
    sets::PROGRESS_BUDGET.store(0, Ordering::Relaxed);
    PROGRESS_ROLLS.store(0, Ordering::Relaxed);
}

/// (augment rolls simulated, combinations tried, current roll budget, stop requested)
#[pyfunction]
fn search_progress() -> (u64, u64, u64, bool) {
    (
        PROGRESS_ROLLS.load(Ordering::Relaxed),
        sets::PROGRESS_NODES.load(Ordering::Relaxed),
        sets::PROGRESS_BUDGET.load(Ordering::Relaxed),
        sets::CANCEL.load(Ordering::Relaxed),
    )
}

/// One piece in `augment_candidates`: per augment type its generator, and the states of this round.
struct AugJob {
    key: u32,
    table: i32,
    cost: i32,
    skills: Vec<(i32, i32)>,
    base_slots: Vec<i32>,
    base_caps: [i32; 5],
    base_lv: Vec<i32>,
    base_ub: f64,
    /// (augment type, stream index, generator)
    rngs: Vec<(i32, usize, core::Rng)>,
    /// per type: the state after each augment of this round
    trace: Vec<Vec<[u32; 4]>>,
    kept: Frontier,
    /// (row without the stream, stream index)
    out: Vec<(AugTuple, usize)>,
}

/// The augments of the next `count` rolls of every piece and type that make the piece better: a
/// `relevant` skill level or slot capacity more, or (with `weights`) a higher score. A later roll is
/// dropped when an earlier one of the same piece already has at least its relevant levels, slot
/// capacity and score. `generators` = the 56 saved states.
///
/// Also where every piece's stream of each sequence is (see `qurious_core::sets::Sync`): an augment
/// draws a different number of times on some pieces, so after a roll two pieces of one sequence can
/// be at different places of it. Returns (rows, lineage per stream, first split step per sequence);
/// the stream of a row is its group after the last roll (pieces that never split share it).
#[pyfunction]
#[pyo3(signature = (tables, pieces, generators, types, count, relevant, weights, slot_values))]
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
fn augment_candidates(
    py: Python<'_>,
    tables: &Tables,
    pieces: Vec<PieceArgs>,
    generators: Vec<[u32; 4]>,
    types: Vec<i32>,
    count: u32,
    relevant: Vec<i32>,
    weights: HashMap<i32, f64>,
    slot_values: [f64; 5],
) -> (Vec<AugTuple>, HashMap<i32, Vec<(u32, i32)>>, HashMap<i32, u32>) {
    let t = tables.0.clone();
    py.allow_threads(move || {
        let level = |list: &[(i32, i32)], r: i32| list.iter().filter(|e| e.0 == r).map(|e| e.1).sum::<i32>();
        // streams: (sequence) per (piece, type)
        let mut stream_seq: Vec<usize> = Vec::new();
        let mut jobs: Vec<AugJob> = pieces
            .into_iter()
            .map(|(key, table, cost, skills, nums)| {
                let base_slots = core::expand_slots(&nums);
                let rngs: Vec<(i32, usize, core::Rng)> = types
                    .iter()
                    .filter_map(|&ty| {
                        let seq = core::seed_index(cost, ty);
                        let g = generators.get(seq)?;
                        stream_seq.push(seq);
                        Some((ty, stream_seq.len() - 1, core::Rng::new(*g)))
                    })
                    .collect();
                AugJob {
                    key,
                    table,
                    cost,
                    base_caps: slot_caps(&base_slots),
                    base_lv: relevant.iter().map(|&r| level(&skills, r)).collect(),
                    base_ub: ub(&weights, &slot_values, &skills, &base_slots),
                    trace: vec![Vec::with_capacity(AUG_ROUND as usize); rngs.len()],
                    base_slots,
                    skills,
                    rngs,
                    kept: Frontier::default(),
                    out: Vec::new(),
                }
            })
            .collect();
        // where each stream's state of this round is: (job, type index)
        let mut place = vec![(0usize, 0usize); stream_seq.len()];
        for (j, job) in jobs.iter().enumerate() {
            for (i, r) in job.rngs.iter().enumerate() {
                place[r.1] = (j, i);
            }
        }
        let mut by_seq: HashMap<usize, Vec<usize>> = HashMap::new();
        for (s, &seq) in stream_seq.iter().enumerate() {
            by_seq.entry(seq).or_default().push(s);
        }
        // groups start as the sequence (same saved state); a split gives the streams that moved away new ids
        let mut group: Vec<i32> = stream_seq.iter().map(|&q| q as i32).collect();
        let mut lineage: Vec<Vec<(u32, i32)>> = group.iter().map(|&g| vec![(0, g)]).collect();
        let mut split: HashMap<i32, u32> = HashMap::new();
        let mut fresh = 1_000i32;
        let mut first = 1u32;
        while first <= count {
            let last = count.min(first.saturating_add(AUG_ROUND - 1));
            jobs.par_iter_mut().for_each(|job| {
                let AugJob { key, table, cost, skills, base_slots, base_caps, base_lv, base_ub, rngs, trace, kept, out } = job;
                let mut buf = Vec::with_capacity(8);
                for tr in trace.iter_mut() {
                    tr.clear();
                }
                for n in first..=last {
                    for (i, (ty, sidx, rng)) in rngs.iter_mut().enumerate() {
                        core::create_result(rng, &t, *table, *cost, skills, *ty, &mut buf);
                        trace[i].push(rng.state());
                        let s = core::summarize(&buf);
                        let mut levels = skills.clone();
                        for &(sid, v) in &s.skills {
                            match levels.iter_mut().find(|(x, _)| *x == sid) {
                                Some(e) => e.1 += v,
                                None => levels.push((sid, v)),
                            }
                        }
                        levels.retain(|e| e.1 > 0);
                        let slots_v = if s.slots != 0 {
                            core::apply_slot_bonus(base_slots, s.slots)
                        } else {
                            base_slots.clone()
                        };
                        let caps = slot_caps(&slots_v);
                        let lv: Vec<i32> = relevant.iter().map(|&r| level(&levels, r)).collect();
                        let value = ub(&weights, &slot_values, &levels, &slots_v);
                        let better = lv.iter().zip(base_lv.iter()).any(|(a, b)| a > b)
                            || (1..=4).any(|l| caps[l] > base_caps[l])
                            || value > *base_ub;
                        if !better {
                            continue;
                        }
                        let mut slots = [0u8; 3];
                        for (o, v) in slots.iter_mut().zip(&slots_v) {
                            *o = (*v).clamp(0, 4) as u8;
                        }
                        if kept.admit(lv, caps, value) {
                            let mut delta: Vec<(i32, i32)> = Vec::new();
                            for &(sid, v) in &s.skills {
                                match delta.iter_mut().find(|e| e.0 == sid) {
                                    Some(e) => e.1 += v,
                                    None => delta.push((sid, v)),
                                }
                            }
                            delta.retain(|e| e.1 != 0);
                            out.push((
                                (*key, *ty, n, levels, slots, s.defense, s.resistances, delta, s.slots, -1),
                                *sidx,
                            ));
                        }
                    }
                }
            });
            // compare the streams of each sequence after every augment of the round
            let mut seqs: Vec<&usize> = by_seq.keys().collect();
            seqs.sort_unstable();
            for &seq in seqs {
                let members = &by_seq[&seq];
                for k in 0..=(last - first) as usize {
                    let step = first + k as u32;
                    let state = |s: usize| {
                        let (j, i) = place[s];
                        jobs[j].trace[i][k]
                    };
                    let s0 = state(members[0]);
                    if members.iter().all(|&s| group[s] == group[members[0]] && state(s) == s0) {
                        continue;
                    }
                    let mut seen: HashMap<(i32, [u32; 4]), i32> = HashMap::new();
                    let mut kept_id: std::collections::HashSet<i32> = std::collections::HashSet::new();
                    for &s in members {
                        let g = group[s];
                        let id = *seen.entry((g, state(s))).or_insert_with(|| {
                            if kept_id.insert(g) {
                                g
                            } else {
                                fresh += 1;
                                fresh
                            }
                        });
                        if id != g {
                            group[s] = id;
                            lineage[s].push((step, id));
                            split.entry(seq as i32).or_insert(step);
                        }
                    }
                }
            }
            PROGRESS_ROLLS.store(last as u64, Ordering::Relaxed);
            first = last.saturating_add(1);
            if last == u32::MAX || sets::CANCEL.load(Ordering::Relaxed) {
                break;
            }
        }
        let mut lineage_of: HashMap<i32, Vec<(u32, i32)>> = HashMap::new();
        for (s, l) in lineage.into_iter().enumerate() {
            lineage_of.entry(group[s]).or_insert(l);
        }
        let rows = jobs
            .into_iter()
            .flat_map(|j| j.out)
            .map(|(mut row, s)| {
                row.9 = group[s];
                row
            })
            .collect();
        (rows, lineage_of, split)
    })
}

/// (roll, skills, slot levels, unsure)
type MeldCand = (u32, Vec<(i32, i32)>, [i32; 3], bool);

/// The next `count` talismans of a method that have a `relevant` skill, a slot or (with `weights`) a
/// score; of those with the same relevant levels and slots only the first, or a later one with a
/// higher score.
#[pyfunction]
#[pyo3(signature = (tables, method, target, state, count, relevant, weights, slot_values))]
#[allow(clippy::too_many_arguments)]
fn meld_candidates(
    py: Python<'_>,
    tables: &MeldTables,
    method: i32,
    target: Option<i32>,
    state: [u32; 4],
    count: u32,
    relevant: Vec<i32>,
    weights: HashMap<i32, f64>,
    slot_values: [f64; 5],
) -> PyResult<Vec<MeldCand>> {
    let tables = tables.0.clone();
    py.allow_threads(move || -> Result<Vec<MeldCand>, String> {
        let mut m = meld::Melder::new(&tables, method, target, [None, None])?;
        let mut rng = core::Rng::new(state);
        let mut kept = Frontier::default();
        let mut out = Vec::new();
        for n in 1..=count {
            let t = m.talisman(&mut rng);
            let lv: Vec<i32> = relevant
                .iter()
                .map(|r| t.skills.iter().filter(|e| e.0 == *r).map(|e| e.1).sum())
                .collect();
            let value = ub(&weights, &slot_values, &t.skills, &t.slots);
            if lv.iter().all(|&x| x == 0) && t.slots[0] == 0 && value <= 0.0 {
                continue;
            }
            if kept.admit(lv, slot_caps(&t.slots), value) {
                out.push((n, t.skills.clone(), t.slots, t.unsure));
            }
        }
        Ok(out)
    })
    .map_err(pyo3::exceptions::PyValueError::new_err)
}


// ---- planner: walking a sequence with the pieces really augmented ------------------------------------

/// (defense, slot points, resistances, skill changes merged and sorted)
type Outcome = (i32, i32, [i32; 5], Vec<(i32, i32)>);

fn outcome(s: &core::Summary) -> Outcome {
    let mut skills: Vec<(i32, i32)> = Vec::new();
    for &(sid, v) in &s.skills {
        match skills.iter_mut().find(|e| e.0 == sid) {
            Some(e) => e.1 += v,
            None => skills.push((sid, v)),
        }
    }
    skills.retain(|e| e.1 != 0);
    skills.sort_unstable();
    (s.defense, s.slots, s.resistances, skills)
}

/// Augments `count` times one piece (table, cost, skills) with one option from `state`: the state
/// afterwards and the outcome of the last augment.
#[pyfunction]
fn augment_advance(
    tables: &Tables,
    state: [u32; 4],
    table: i32,
    cost: i32,
    skills: Vec<(i32, i32)>,
    buildup_type: i32,
    count: u32,
) -> ([u32; 4], Option<Outcome>) {
    let mut rng = core::Rng::new(state);
    let mut buf = Vec::with_capacity(8);
    let mut last = None;
    for _ in 0..count {
        core::create_result(&mut rng, &tables.0, table, cost, &skills, buildup_type, &mut buf);
        last = Some(outcome(&core::summarize(&buf)));
    }
    (rng.state(), last)
}

/// Like `augment_find`, but the augments before the wanted one go on another piece (`burn`: table,
/// cost, skills): after j augments of `burn`, one augment of the target piece; the first j that gives
/// `expected`: (j + 1, state after it), or None within `limit` augments.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn augment_find_via(
    py: Python<'_>,
    tables: &Tables,
    state: [u32; 4],
    burn: (i32, i32, Vec<(i32, i32)>),
    target: (i32, i32, Vec<(i32, i32)>),
    buildup_type: i32,
    expected: Outcome,
    limit: u64,
) -> Option<(u64, [u32; 4])> {
    let t = tables.0.clone();
    let mut expected = expected;
    expected.3.sort_unstable();
    py.allow_threads(move || {
        let mut rng = core::Rng::new(state);
        let mut buf = Vec::with_capacity(8);
        for n in 1..=limit {
            let mut tr = core::Rng::new(rng.state());
            core::create_result(&mut tr, &t, target.0, target.1, &target.2, buildup_type, &mut buf);
            if outcome(&core::summarize(&buf)) == expected {
                return Some((n, tr.state()));
            }
            core::create_result(&mut rng, &t, burn.0, burn.1, &burn.2, buildup_type, &mut buf);
        }
        None
    })
}

/// Augments one piece again and again from `state` until an augment gives `expected` (defense, slot
/// points, resistances and skill changes): (how many augments, state after the last one), or None
/// within `limit`.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn augment_find(
    py: Python<'_>,
    tables: &Tables,
    state: [u32; 4],
    table: i32,
    cost: i32,
    skills: Vec<(i32, i32)>,
    buildup_type: i32,
    expected: Outcome,
    limit: u64,
) -> Option<(u64, [u32; 4])> {
    let t = tables.0.clone();
    let mut expected = expected;
    expected.3.sort_unstable();
    py.allow_threads(move || {
        let mut rng = core::Rng::new(state);
        let mut buf = Vec::with_capacity(8);
        for n in 1..=limit {
            core::create_result(&mut rng, &t, table, cost, &skills, buildup_type, &mut buf);
            if outcome(&core::summarize(&buf)) == expected {
                return Some((n, rng.state()));
            }
        }
        None
    })
}

/// Melds talismans of one method (and picked skill) from `state`, reloaded save (empty carried
/// table), until one has `skills` and `slots`: (how many talismans, state after it), or None.
#[pyfunction]
#[pyo3(signature = (tables, method, target, state, skills, slots, limit))]
#[allow(clippy::too_many_arguments)]
fn meld_find(
    py: Python<'_>,
    tables: &MeldTables,
    method: i32,
    target: Option<i32>,
    state: [u32; 4],
    skills: Vec<(i32, i32)>,
    slots: [i32; 3],
    limit: u64,
) -> PyResult<Option<(u64, [u32; 4])>> {
    let tables = tables.0.clone();
    py.allow_threads(move || -> Result<Option<(u64, [u32; 4])>, String> {
        let mut m = meld::Melder::new(&tables, method, target, [None, None])?;
        let mut rng = core::Rng::new(state);
        for n in 1..=limit {
            let t = m.talisman(&mut rng);
            if t.skills == skills && t.slots == slots {
                return Ok(Some((n, rng.state())));
            }
        }
        Ok(None)
    })
    .map_err(pyo3::exceptions::PyValueError::new_err)
}

// ---- the saved sets' plan as a fixed path (Set builder / optimizer with saved sets) -------------------

/// (table, cost, skills, augments) of one stretch of a path
type Segment = (i32, i32, Vec<(i32, i32)>, u32);

/// The states of one sequence along a path: from `state`, with augment option `buildup_type`, each
/// segment's piece augmented that many times in turn. Returns the state before the first augment and
/// after every augment (length = augments + 1).
#[pyfunction]
fn augment_path(
    py: Python<'_>,
    tables: &Tables,
    state: [u32; 4],
    buildup_type: i32,
    segments: Vec<Segment>,
) -> Vec<[u32; 4]> {
    let t = tables.0.clone();
    py.allow_threads(move || {
        let mut rng = core::Rng::new(state);
        let mut buf = Vec::with_capacity(8);
        let mut out = vec![rng.state()];
        for (table, cost, skills, count) in &segments {
            for _ in 0..*count {
                core::create_result(&mut rng, &t, *table, *cost, skills, buildup_type, &mut buf);
                out.push(rng.state());
            }
        }
        out
    })
}

/// Augments that can be taken from inside a fixed path without changing it: for every piece, each
/// augment k of the path (1-based, not in `reserved`) where augmenting this piece instead of the
/// path's piece leaves the generator at the same place (so every later augment of the path comes the
/// same), when it makes the piece better (as in `augment_candidates`; a later one only if no earlier
/// one of the piece already has at least its relevant levels, slot capacity and score). `path` comes
/// from `augment_path`. Rows as `augment_candidates` with roll = k and stream = -1.
#[pyfunction]
#[pyo3(signature = (tables, path, reserved, pieces, buildup_type, relevant, weights, slot_values))]
#[allow(clippy::too_many_arguments)]
fn path_candidates(
    py: Python<'_>,
    tables: &Tables,
    path: Vec<[u32; 4]>,
    reserved: Vec<u32>,
    pieces: Vec<PieceArgs>,
    buildup_type: i32,
    relevant: Vec<i32>,
    weights: HashMap<i32, f64>,
    slot_values: [f64; 5],
) -> Vec<AugTuple> {
    let t = tables.0.clone();
    py.allow_threads(move || {
        let level = |list: &[(i32, i32)], r: i32| list.iter().filter(|e| e.0 == r).map(|e| e.1).sum::<i32>();
        let reserved: std::collections::HashSet<u32> = reserved.into_iter().collect();
        pieces
            .par_iter()
            .flat_map_iter(|(key, table, cost, skills, nums)| {
                let base_slots = core::expand_slots(nums);
                let base_caps = slot_caps(&base_slots);
                let base_lv: Vec<i32> = relevant.iter().map(|&r| level(skills, r)).collect();
                let base_ub = ub(&weights, &slot_values, skills, &base_slots);
                let mut kept = Frontier::default();
                let mut out = Vec::new();
                let mut buf = Vec::with_capacity(8);
                for k in 1..path.len() {
                    if reserved.contains(&(k as u32)) {
                        continue;
                    }
                    let mut rng = core::Rng::new(path[k - 1]);
                    core::create_result(&mut rng, &t, *table, *cost, skills, buildup_type, &mut buf);
                    if rng.state() != path[k] {
                        continue;
                    }
                    let s = core::summarize(&buf);
                    let mut levels = skills.clone();
                    for &(sid, v) in &s.skills {
                        match levels.iter_mut().find(|(x, _)| *x == sid) {
                            Some(e) => e.1 += v,
                            None => levels.push((sid, v)),
                        }
                    }
                    levels.retain(|e| e.1 > 0);
                    let slots_v = if s.slots != 0 {
                        core::apply_slot_bonus(&base_slots, s.slots)
                    } else {
                        base_slots.clone()
                    };
                    let caps = slot_caps(&slots_v);
                    let lv: Vec<i32> = relevant.iter().map(|&r| level(&levels, r)).collect();
                    let value = ub(&weights, &slot_values, &levels, &slots_v);
                    let better = lv.iter().zip(&base_lv).any(|(a, b)| a > b)
                        || (1..=4).any(|l| caps[l] > base_caps[l])
                        || value > base_ub;
                    if !better || !kept.admit(lv, caps, value) {
                        continue;
                    }
                    let mut slots = [0u8; 3];
                    for (o, v) in slots.iter_mut().zip(&slots_v) {
                        *o = (*v).clamp(0, 4) as u8;
                    }
                    let mut delta: Vec<(i32, i32)> = Vec::new();
                    for &(sid, v) in &s.skills {
                        match delta.iter_mut().find(|e| e.0 == sid) {
                            Some(e) => e.1 += v,
                            None => delta.push((sid, v)),
                        }
                    }
                    delta.retain(|e| e.1 != 0);
                    out.push((*key, buildup_type, k as u32, levels, slots, s.defense, s.resistances, delta, s.slots, -1));
                }
                out
            })
            .collect()
    })
}

/// (skills, slot levels, unsure) of a talisman
type PathTal = (Vec<(i32, i32)>, [i32; 3], bool);

/// The talismans of a melding path: from `state`, each segment's (method, target) melded that many
/// times in turn. Returns every talisman and the state after the last one.
#[pyfunction]
fn meld_path(
    py: Python<'_>,
    tables: &MeldTables,
    state: [u32; 4],
    segments: Vec<(i32, Option<i32>, u32)>,
) -> PyResult<(Vec<PathTal>, [u32; 4])> {
    let tables = tables.0.clone();
    py.allow_threads(move || -> Result<(Vec<PathTal>, [u32; 4]), String> {
        let mut rng = core::Rng::new(state);
        let mut out = Vec::new();
        for (method, target, count) in segments {
            let mut m = meld::Melder::new(&tables, method, target, [None, None])?;
            for _ in 0..count {
                let t = m.talisman(&mut rng);
                out.push((t.skills.clone(), t.slots, t.unsure));
            }
        }
        Ok((out, rng.state()))
    })
    .map_err(pyo3::exceptions::PyValueError::new_err)
}

impl Drop for Scan {
    fn drop(&mut self) {
        self.0.cancel.store(true, Ordering::Relaxed);
    }
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Tables>()?;
    m.add_class::<Scan>()?;
    m.add_function(wrap_pyfunction!(create_result, m)?)?;
    m.add_function(wrap_pyfunction!(rolls, m)?)?;
    m.add_class::<MeldTables>()?;
    m.add_function(wrap_pyfunction!(meld_rolls, m)?)?;
    m.add_function(wrap_pyfunction!(meld_scan, m)?)?;
    m.add_function(wrap_pyfunction!(set_search, m)?)?;
    m.add_function(wrap_pyfunction!(set_improve, m)?)?;
    m.add_function(wrap_pyfunction!(augment_candidates, m)?)?;
    m.add_function(wrap_pyfunction!(search_cancel, m)?)?;
    m.add_function(wrap_pyfunction!(augment_path, m)?)?;
    m.add_function(wrap_pyfunction!(path_candidates, m)?)?;
    m.add_function(wrap_pyfunction!(meld_path, m)?)?;
    m.add_function(wrap_pyfunction!(search_reset, m)?)?;
    m.add_function(wrap_pyfunction!(search_progress, m)?)?;
    m.add_function(wrap_pyfunction!(meld_candidates, m)?)?;
    m.add_function(wrap_pyfunction!(augment_advance, m)?)?;
    m.add_function(wrap_pyfunction!(augment_find, m)?)?;
    m.add_function(wrap_pyfunction!(augment_find_via, m)?)?;
    m.add_function(wrap_pyfunction!(meld_find, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
