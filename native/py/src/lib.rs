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
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
