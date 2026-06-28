"""Tests for the materialized current-state histogram (ADR-020).

The central guarantee: maintaining the state incrementally (batch by batch)
yields exactly the same result as rebuilding it from the full fact. That
equality is what makes the materialized table a trustworthy, rebuildable cache.
"""

import random

from binmoments.serving import CurrentStateHistogram, increments_to_items


class _Row:
    """Minimal stand-in for an increment-fact row."""

    def __init__(self, instrument_id, bin_schema_id, event_hour, bin_index, count_delta):
        self.instrument_id = instrument_id
        self.bin_schema_id = bin_schema_id
        self.event_hour = event_hour
        self.bin_index = bin_index
        self.count_delta = count_delta


def _key(inst, schema, hour, b):
    return (inst, schema, hour, b)


def test_single_reading_increments_its_bin():
    cs = CurrentStateHistogram()
    cs.apply(_key("I1", "S1", "2024-06-10T00", 3), +1)
    assert cs.counts[_key("I1", "S1", "2024-06-10T00", 3)] == 1


def test_zeroed_bin_is_dropped():
    cs = CurrentStateHistogram()
    cs.apply(_key("I1", "S1", "2024-06-10T00", 3), +1)
    cs.apply(_key("I1", "S1", "2024-06-10T00", 3), -1)
    assert len(cs) == 0  # sparse: a bin with no mass is absent


def test_incremental_equals_rebuild_random():
    """The keystone: applying deltas in arbitrary batches equals rebuilding
    from all deltas at once. True because bin counts form a commutative monoid."""
    rng = random.Random(7)
    items = []
    for _ in range(2000):
        key = _key(
            rng.choice(["I1", "I2"]),
            "S1",
            f"2024-06-{rng.randint(10, 28):02d}T{rng.randint(0, 23):02d}",
            rng.randint(0, 31),
        )
        items.append((key, rng.choice([+1, +1, +1, -1])))  # mostly inserts, some corrections

    # Rebuild from scratch.
    rebuilt = CurrentStateHistogram.rebuild(items)

    # Incremental: shuffle and apply in random-sized batches, different order.
    shuffled = items[:]
    rng.shuffle(shuffled)
    incremental = CurrentStateHistogram()
    i = 0
    while i < len(shuffled):
        batch = shuffled[i : i + rng.randint(1, 50)]
        incremental.apply_many(batch)
        i += len(batch)

    assert incremental == rebuilt  # order and batching must not matter


def test_correction_moves_mass_between_bins():
    """A correction (retract old bin, assert new bin) nets to moving one count."""
    cs = CurrentStateHistogram()
    hour = "2024-06-10T00"
    cs.apply(_key("I1", "S1", hour, 5), +1)        # original reading -> bin 5
    cs.apply(_key("I1", "S1", hour, 5), -1)        # correction retracts bin 5
    cs.apply(_key("I1", "S1", hour, 8), +1)        # correction asserts bin 8
    assert _key("I1", "S1", hour, 5) not in cs.counts
    assert cs.counts[_key("I1", "S1", hour, 8)] == 1


def test_merge_is_additive():
    a = CurrentStateHistogram().apply_many([(_key("I1", "S1", "h0", 1), +2)])
    b = CurrentStateHistogram().apply_many([(_key("I1", "S1", "h0", 1), +3),
                                            (_key("I1", "S1", "h0", 2), +1)])
    a.merge(b)
    assert a.counts[_key("I1", "S1", "h0", 1)] == 5
    assert a.counts[_key("I1", "S1", "h0", 2)] == 1


def test_increments_to_items_adapter():
    rows = [
        _Row("I1", "S1", "h0", 3, +1),
        _Row("I1", "S1", "h0", 3, +1),
        _Row("I1", "S1", "h0", 7, +1),
    ]
    cs = CurrentStateHistogram.rebuild(increments_to_items(rows))
    assert cs.counts[_key("I1", "S1", "h0", 3)] == 2
    assert cs.counts[_key("I1", "S1", "h0", 7)] == 1


def test_fast_reads():
    cs = CurrentStateHistogram().apply_many([
        (_key("I1", "S1", "h0", 1), +2),
        (_key("I1", "S1", "h1", 1), +3),
        (_key("I1", "S1", "h0", 2), +1),
        (_key("I2", "S1", "h0", 1), +9),  # other instrument, must not leak in
    ])
    # bin_totals sums over hours for one instrument/schema
    assert cs.bin_totals("I1", "S1") == {1: 5, 2: 1}
    # histogram keeps the hour grain
    assert cs.histogram("I1", "S1") == {("h0", 1): 2, ("h1", 1): 3, ("h0", 2): 1}
