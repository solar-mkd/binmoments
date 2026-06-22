"""Tests for the bitemporal increment fact (ADR-004).

These encode what ADR-004 promises:
- ingestion produces +1 measurement deltas in the right bins and event-hours;
- as-of reproducibility: the histogram as known at a past instant excludes later arrivals;
- late data changes the current picture without erasing what was known before;
- corrections are compensating deltas (append-only) — total mass preserved, nothing mutated;
- horizon materialization filters by arrival within (event_hour + horizon);
- the merge guard refuses to sum counts across different bin_schema_id values (ADR-003);
- end-to-end: ingesting a year of simulated readings reproduces the direct histogram.
"""
from datetime import datetime, timedelta

import pytest

from binmoments.binning import BinSchema
from binmoments.fact import EntryType, IncrementFact, IncrementRow, floor_to_hour


SCHEMA_A = "bm_aaaaaaaaaaaa"
SCHEMA_B = "bm_bbbbbbbbbbbb"
H = datetime(2024, 6, 2, 13, 0, 0)  # an event hour


def _row(bin_, arrival, *, delta=1, value=21.0, schema=SCHEMA_A, entry=EntryType.MEASUREMENT):
    return IncrementRow(
        instrument_id="TEMP-001",
        channel="temperature",
        bin_schema_id=schema,
        bin=bin_,
        event_hour=H,
        arrival_time=arrival,
        delta=delta,
        value=value,
        entry_type=entry,
    )


def test_floor_to_hour():
    assert floor_to_hour(datetime(2024, 6, 2, 13, 47, 12)) == datetime(2024, 6, 2, 13, 0, 0)


def test_as_of_excludes_later_arrivals():
    fact = IncrementFact()
    early = H + timedelta(minutes=5)
    late = H + timedelta(days=2)
    fact.append(_row(3, early))       # known soon after the hour
    fact.append(_row(7, late))        # a late arrival, two days later, different bin

    # As of just after the early arrival: only the first reading is known.
    snap_then = fact.as_of(early + timedelta(minutes=1), instrument_id="TEMP-001", channel="temperature")
    assert snap_then == {3: 1}

    # Current (all arrivals): both are known.
    snap_now = fact.current(instrument_id="TEMP-001", channel="temperature")
    assert snap_now == {3: 1, 7: 1}


def test_correction_is_compensating_and_append_only():
    fact = IncrementFact()
    t0 = H + timedelta(minutes=5)
    fact.append(_row(3, t0))                      # reading lands in bin 3
    rows_before = len(fact)

    t_corr = H + timedelta(days=1)
    fact.apply_correction(
        instrument_id="TEMP-001",
        channel="temperature",
        bin_schema_id=SCHEMA_A,
        event_hour=H,
        from_bin=3,
        to_bin=5,
        from_value=21.0,
        to_value=27.0,
        arrival_time=t_corr,
    )

    # Before the correction was known: still bin 3.
    assert fact.as_of(t0 + timedelta(minutes=1), instrument_id="TEMP-001", channel="temperature") == {3: 1}
    # After: moved to bin 5, bin 3 emptied (dropped from the sparse map). Mass preserved.
    assert fact.current(instrument_id="TEMP-001", channel="temperature") == {5: 1}
    # Append-only: two rows added, the original row still present unchanged.
    assert len(fact) == rows_before + 2
    assert _row(3, t0) in fact.rows


def test_horizon_materialization_filters_by_arrival():
    fact = IncrementFact()
    fact.append(_row(3, H + timedelta(minutes=10)))   # within the hour
    fact.append(_row(7, H + timedelta(days=2)))        # arrives 2 days late

    one_hour = fact.histogram_at_horizon(H, timedelta(hours=1), instrument_id="TEMP-001", channel="temperature")
    seven_day = fact.histogram_at_horizon(H, timedelta(days=7), instrument_id="TEMP-001", channel="temperature")
    final = fact.histogram_at_horizon(H, None, instrument_id="TEMP-001", channel="temperature")

    assert one_hour == {3: 1}            # the late row hasn't arrived within 1h
    assert seven_day == {3: 1, 7: 1}     # within 7 days, both present
    assert final == {3: 1, 7: 1}         # final = all arrivals


def test_merge_guard_refuses_to_mix_schema_versions():
    fact = IncrementFact()
    fact.append(_row(3, H + timedelta(minutes=5), schema=SCHEMA_A))
    fact.append(_row(3, H + timedelta(minutes=5), schema=SCHEMA_B))

    with pytest.raises(ValueError):
        fact.current(instrument_id="TEMP-001", channel="temperature")  # ambiguous: two schemas

    # Naming a schema is fine.
    assert fact.current(instrument_id="TEMP-001", channel="temperature", bin_schema_id=SCHEMA_A) == {3: 1}


def test_changes_between_returns_new_information():
    fact = IncrementFact()
    t1 = H + timedelta(minutes=5)
    t2 = H + timedelta(days=1)
    fact.append(_row(3, t1))
    fact.append(_row(7, t2))
    changed = fact.changes_between(t1, t2, instrument_id="TEMP-001", channel="temperature")
    assert len(changed) == 1
    assert changed[0].bin == 7


def test_end_to_end_ingest_year_matches_direct_histogram():
    from binmoments.simulator import Simulator
    from binmoments.binning import derive_bin_schema

    sim = Simulator(
        instrument_id="TEMP-001",
        start=datetime(2024, 1, 1),
        end=datetime(2025, 1, 1),
        sampling_per_hour=1,
        seed=3,
    )
    records, _ = sim.run()
    values = [r["values"]["temperature"] for r in records]
    schema = derive_bin_schema(
        values, scope="instrument:TEMP-001", channel="temperature", target_bin_count=64,
        fit_start="2024-01-01T00:00:00", fit_end="2025-01-01T00:00:00", created_at="2025-01-01T00:00:00",
    )

    fact = IncrementFact()
    added = fact.ingest_records(records, schema)
    assert added == len(records)

    # The current histogram over ALL event-hours equals binning the values directly.
    current_all = fact.current(instrument_id="TEMP-001", channel="temperature")
    assert current_all == schema.bin_counts(values)
