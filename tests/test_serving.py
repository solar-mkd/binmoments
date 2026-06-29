"""Tests for the serving layer (ADR-020): collapsed current-state histogram and
schema-edge export.

The central guarantee for the current-state histogram: maintaining it
incrementally equals rebuilding it from the full fact. That equality is what
makes the materialized table a trustworthy, rebuildable cache.
"""

import random

from binmoments.serving import (
    CurrentStateHistogram,
    increments_to_items,
    schema_edge_rows,
)


class _Row:
    """Minimal stand-in for an increment-fact row (carries an hour that the
    collapsed current state must ignore)."""

    def __init__(self, instrument_id, bin_schema_id, event_hour, bin_index, count_delta):
        self.instrument_id = instrument_id
        self.bin_schema_id = bin_schema_id
        self.event_hour = event_hour
        self.bin_index = bin_index
        self.count_delta = count_delta


def _k(inst, schema, b):
    return (inst, schema, b)


# -- current-state histogram ----------------------------------------------

def test_single_reading_increments_its_bin():
    cs = CurrentStateHistogram().apply(_k("I1", "S1", 3), +1)
    assert cs.counts[_k("I1", "S1", 3)] == 1


def test_zeroed_bin_is_dropped():
    cs = CurrentStateHistogram()
    cs.apply(_k("I1", "S1", 3), +1).apply(_k("I1", "S1", 3), -1)
    assert len(cs) == 0


def test_hours_collapse_into_one_bin_total():
    """Deltas from different hours but the same bin sum into one current count."""
    rows = [
        _Row("I1", "S1", "2024-06-10T00", 4, +1),
        _Row("I1", "S1", "2024-06-10T01", 4, +1),
        _Row("I1", "S1", "2024-06-11T09", 4, +1),
    ]
    cs = CurrentStateHistogram.rebuild(increments_to_items(rows))
    assert cs.counts[_k("I1", "S1", 4)] == 3      # all three hours collapsed


def test_incremental_equals_rebuild_random():
    """The keystone: applying deltas in arbitrary batches equals rebuilding from
    all deltas at once (commutative monoid)."""
    rng = random.Random(7)
    items = []
    for _ in range(2000):
        key = _k(rng.choice(["I1", "I2"]), "S1", rng.randint(0, 31))
        items.append((key, rng.choice([+1, +1, +1, -1])))

    rebuilt = CurrentStateHistogram.rebuild(items)

    shuffled = items[:]
    rng.shuffle(shuffled)
    incremental = CurrentStateHistogram()
    i = 0
    while i < len(shuffled):
        batch = shuffled[i : i + rng.randint(1, 50)]
        incremental.apply_many(batch)
        i += len(batch)

    assert incremental == rebuilt


def test_correction_moves_mass_between_bins():
    cs = CurrentStateHistogram()
    cs.apply(_k("I1", "S1", 5), +1)   # original reading -> bin 5
    cs.apply(_k("I1", "S1", 5), -1)   # correction retracts bin 5
    cs.apply(_k("I1", "S1", 8), +1)   # correction asserts bin 8
    assert _k("I1", "S1", 5) not in cs.counts
    assert cs.counts[_k("I1", "S1", 8)] == 1


def test_distribution_read_isolates_instrument():
    cs = CurrentStateHistogram().apply_many([
        (_k("I1", "S1", 1), +5),
        (_k("I1", "S1", 2), +1),
        (_k("I2", "S1", 1), +9),   # other instrument must not leak in
    ])
    assert cs.distribution("I1", "S1") == {1: 5, 2: 1}


# -- schema export ---------------------------------------------------------

class _Schema:
    def __init__(self, edges):
        self.edges = edges


def test_schema_edge_rows_basic():
    rows = schema_edge_rows(_Schema([0.0, 1.0, 3.0, 6.0]))
    assert rows == [(0, 0.0, 1.0, 0.5), (1, 1.0, 3.0, 2.0), (2, 3.0, 6.0, 4.5)]


def test_schema_edge_rows_open_outer_bins():
    rows = schema_edge_rows(_Schema([float("-inf"), 2.0, float("inf")]))
    assert rows[0][1] == float("-inf") and rows[0][3] == 2.0   # midpoint -> finite neighbour
    assert rows[1][2] == float("inf") and rows[1][3] == 2.0


def test_schema_edge_rows_custom_attr():
    class S2:
        def __init__(self):
            self.bin_edges = [0.0, 2.0, 4.0]
    rows = schema_edge_rows(S2(), edges_attr="bin_edges")
    assert len(rows) == 2
