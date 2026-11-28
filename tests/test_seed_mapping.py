"""Regressions from the game's calcRandomSeed and the observed Kaiser roll."""
import pytest

from qurious_predictor import engine, planner
from qurious_predictor.rng import XorShift128


@pytest.mark.parametrize('cost,expected', [
    (10, [32, 33, 34, 35]), (12, [35, 35, 35, 35]),
    (14, [38, 37, 36, 35]), (16, [41, 39, 37, 35]),
    (18, [44, 41, 38, 35]), (20, [47, 43, 39, 35]),
])
def test_game_seed_selection(cost, expected):
    assert [engine.seed_index(cost, ty) for ty in range(4)] == expected


def test_shared_stream_is_planned_once_and_walked_with_each_steps_option(monkeypatch):
    """A normal roll and a Skills+ roll at cost 12 advance the same generator."""
    class Native:
        def search_progress(self): return (0, 0, 0, False)
        def augment_find(self, nt, state, table, cost, skills, ty, expected, limit):
            wanted = expected[0]
            n = wanted - state[0]
            return (n, [wanted, 0, 0, 0]) if 0 < n <= limit else None
        def augment_find_via(self, *args): return None
        def augment_path(self, nt, state, ty, segs):
            calls.append(ty)
            out = [state]
            for *_, count in segs:
                for _ in range(count): out.append([out[-1][0] + 1, 0, 0, 0])
            return out
    calls = []
    monkeypatch.setattr(planner, '_native', lambda: Native())
    monkeypatch.setattr(planner.search, 'native_tables', lambda data: None)
    data = {'armors': {str(i): {'table': 5, 'cost': 12, 'skills': []} for i in (1, 2)},
            'all_armors': {str(i): {'rare': 8} for i in (1, 2)},
            'costs': {'armor': {'9': {'zenny': 1, 'points': {'0': 1, '1': 1}}}}}
    targets = [{'id': str(i), 'name': str(i), 'cost': 12, 'type': ty, 'n': n,
                'expected': [n, 0, [0]*5, []]} for i, ty, n in [(1, 0, 2), (2, 1, 5)]]
    gens = [XorShift128((0, 0, 0, 0)) for _ in range(56)]
    p = planner.Planner(data, None)
    groups, missing = p.armor_plan(targets, gens, [])
    assert not missing
    assert len(groups) == 1
    q = groups[0]
    assert q['seed'] == 35 and q['mixed']
    assert [st['augments'] for st in q['steps']] == [2, 3]
    assert p._route(q, None, lambda st: None) == [(i, 0, 0, 0) for i in range(6)]
    assert calls == [0, 1]
