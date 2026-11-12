"""High-level prediction: next N augments of an armor piece for each augment type."""

from __future__ import annotations

from dataclasses import dataclass

from . import engine
from .engine import Summary, Tables
from .rng import XorShift128


@dataclass
class Roll:
    n: int
    summary: Summary
    entries: list[engine.Entry]


def next_rolls(generators: list[XorShift128], tables: Tables, armor: dict, buildup_type: int,
               count: int) -> tuple[int, list[Roll]]:
    """Returns (generator index, rolls). The generator is copied; nothing is modified."""
    seed = engine.seed_index(armor["cost"], buildup_type)
    rng = generators[seed].copy()
    skills = [tuple(x) for x in armor["skills"]]
    rolls = []
    for n in range(1, count + 1):
        entries = engine.create_result(rng, tables, armor["table"], armor["cost"], skills, buildup_type)
        rolls.append(Roll(n, engine.summarize(entries), entries))
    return seed, rolls
