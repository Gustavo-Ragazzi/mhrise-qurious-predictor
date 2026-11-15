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
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
