"""Tests for the synthetic temperature simulator (ADR-008).

These encode what ADR-008 promises:
- determinism: a given seed yields identical output (reproducibility);
- a run with faults differs from a run without them ONLY inside the fault windows (exact ground
  truth) — the property that lets detection be scored, not eyeballed;
- the baseline carries the configured seasonal mean and a diurnal cycle;
- injected mean-shift, variance-inflation, and spike faults appear as specified;
- every injected fault is logged in the ground truth;
- records are JSON-serializable with the expected envelope (event_time AND arrival_time).
"""
import json
import statistics
from datetime import datetime

import pytest

from binmoments.simulator import (
    DriftWindow,
    FaultKind,
    Simulator,
    Spike,
    TemperatureField,
)


def _common(**overrides):
    base = dict(
        instrument_id="TEMP-001",
        start=datetime(2024, 6, 1, 0, 0, 0),
        end=datetime(2024, 6, 4, 0, 0, 0),  # 3 days
        sampling_per_hour=4,
        seed=7,
    )
    base.update(overrides)
    return base


def test_deterministic_given_seed():
    r1, g1 = Simulator(**_common()).run()
    r2, g2 = Simulator(**_common()).run()
    assert r1 == r2
    assert [e.to_dict() for e in g1] == [e.to_dict() for e in g2]


def test_baseline_annual_mean_matches_config():
    fld = TemperatureField()
    sim = Simulator(
        instrument_id="T",
        start=datetime(2024, 1, 1),
        end=datetime(2025, 1, 1),  # a full year
        sampling_per_hour=1,
        seed=1,
        field_model=fld,
    )
    records, _ = sim.run()
    vals = [r["values"]["temperature"] for r in records]
    assert abs(statistics.mean(vals) - fld.annual_mean) < 0.5


def test_daily_cycle_afternoon_warmer_than_predawn():
    sim = Simulator(
        instrument_id="T",
        start=datetime(2024, 6, 1),
        end=datetime(2024, 6, 8),  # a week
        sampling_per_hour=1,
        seed=2,
    )
    records, _ = sim.run()
    by_hour = {}
    for r in records:
        hour = datetime.fromisoformat(r["event_time"]).hour
        by_hour.setdefault(hour, []).append(r["values"]["temperature"])
    assert statistics.mean(by_hour[14]) > statistics.mean(by_hour[4])


def test_mean_shift_drift_is_exact_and_isolated():
    clean, _ = Simulator(**_common()).run()
    window = DriftWindow(
        start=datetime(2024, 6, 2, 0, 0, 0),
        end=datetime(2024, 6, 3, 0, 0, 0),
        kind=FaultKind.MEAN_SHIFT,
        magnitude=5.0,
    )
    drifted, _ = Simulator(**_common(), drift_windows=[window]).run()

    for c, d in zip(clean, drifted):
        when = datetime.fromisoformat(c["event_time"])
        cv = c["values"]["temperature"]
        dv = d["values"]["temperature"]
        if window.start <= when < window.end:
            assert dv == pytest.approx(cv + 5.0)   # exact injected offset
        else:
            assert dv == cv                         # untouched outside the window


def test_variance_inflation_increases_in_window_spread():
    common = _common(sampling_per_hour=60)
    clean, _ = Simulator(**common).run()
    window = DriftWindow(
        start=datetime(2024, 6, 2, 0, 0, 0),
        end=datetime(2024, 6, 2, 12, 0, 0),
        kind=FaultKind.VARIANCE_INFLATION,
        magnitude=3.0,
    )
    inflated, _ = Simulator(**common, drift_windows=[window]).run()

    def in_window(records):
        return [
            r["values"]["temperature"]
            for r in records
            if window.start <= datetime.fromisoformat(r["event_time"]) < window.end
        ]

    assert statistics.pvariance(in_window(inflated)) > statistics.pvariance(in_window(clean))


def test_spike_appears_and_is_logged():
    spike = Spike(at=datetime(2024, 6, 2, 6, 0, 0), value=60.0)
    records, ground_truth = Simulator(**_common(), spikes=[spike]).run()

    near = [
        r["values"]["temperature"]
        for r in records
        if datetime.fromisoformat(r["event_time"]) == spike.at
    ]
    assert 60.0 in near
    assert any(e.kind == FaultKind.SPIKE.value for e in ground_truth)


def test_ground_truth_logs_all_injected_faults():
    window = DriftWindow(
        start=datetime(2024, 6, 2),
        end=datetime(2024, 6, 3),
        kind=FaultKind.MEAN_SHIFT,
        magnitude=4.0,
    )
    spike = Spike(at=datetime(2024, 6, 2, 6, 0, 0), value=55.0)
    _, ground_truth = Simulator(**_common(), drift_windows=[window], spikes=[spike]).run()

    kinds = sorted(e.kind for e in ground_truth)
    assert kinds == sorted([FaultKind.MEAN_SHIFT.value, FaultKind.SPIKE.value])


def test_records_are_json_serializable_with_envelope():
    records, _ = Simulator(**_common()).run()
    blob = json.dumps(records)            # must not raise
    assert blob
    first = records[0]
    for key in ("instrument_id", "measurement_id", "event_time", "arrival_time", "values"):
        assert key in first
    assert "temperature" in first["values"]
