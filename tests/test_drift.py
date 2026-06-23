"""Tests for drift detection (ADR-005) — including the end-to-end ground-truth validation.

These encode what ADR-005 promises and what the simulator's ground truth lets us prove:
- Wasserstein behaves correctly: zero for identical distributions, equal to the shift for a pure
  shift (and so expressed in value units);
- cross-schema comparison works: two distributions on different schemas (e.g. an annual refit) are
  comparable via the shared grid (ADR-016);
- the threshold is self-calibrated above the instrument's normal scatter;
- **the keystone:** injected mean-shift drift is caught in the right window with NO false alarms in
  the quiet stretches (precision AND recall, the two halves);
- honest limit + complement: a pure variance change is subtle for daily Wasserstein (the diurnal
  swing masks it), but shows up directly in the variance moment from the power sums.
"""
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np
import pytest

from binmoments.binning import derive_bin_schema
from binmoments.drift import DriftDetector, calibrate_threshold, wasserstein1, wasserstein1_binned
from binmoments.simulator import DriftWindow, FaultKind, Simulator
from binmoments.stats import PowerSums


def _schema(values, bins=48, scope="instrument:TEMP-001"):
    return derive_bin_schema(values, scope=scope, channel="temperature", target_bin_count=bins,
                             fit_start="a", fit_end="b", created_at="c")


# --- distance behaviour ---------------------------------------------------------------------

def test_wasserstein_zero_for_identical_and_equals_shift():
    rng = np.random.default_rng(0)
    base = rng.normal(20.0, 3.0, 400_000)
    shifted = base + 5.0
    schema = _schema(np.concatenate([base, shifted]), bins=128)
    edges = np.asarray(schema.edges)

    def interior(vals):
        c = schema.bin_counts(vals)
        return np.array([c.get(i, 0) for i in range(1, schema.interior_bin_count + 1)], float)

    assert wasserstein1(edges, interior(base), edges, interior(base)) == pytest.approx(0.0, abs=1e-9)
    assert wasserstein1(edges, interior(base), edges, interior(shifted)) == pytest.approx(5.0, abs=0.2)


def test_cross_schema_comparison_via_grid():
    """Two schemas with different edges (as after an annual refit) remain comparable (ADR-016)."""
    rng = np.random.default_rng(1)
    x = rng.normal(20.0, 3.0, 400_000)
    a = _schema(x[:200_000], bins=32)
    b = _schema(x[200_000:], bins=48)        # same distribution, different edges/resolution
    assert a.schema_id != b.schema_id

    same = wasserstein1_binned(a, a.bin_counts(x), b, b.bin_counts(x))
    assert same < 0.3                         # same underlying distribution -> near zero despite rulers
    shifted = wasserstein1_binned(a, a.bin_counts(x + 3.0), b, b.bin_counts(x))
    assert 2.3 < shifted < 3.7                # a real shift is still ~3, measured across schemas


def test_calibrated_threshold_sits_above_normal_scatter():
    normal = [0.2, 0.25, 0.18, 0.22, 0.3, 0.21, 0.26]
    thr = calibrate_threshold(normal, k=8.0)
    assert thr > max(normal)


# --- the keystone: end-to-end validation against ground truth -------------------------------

def _build_days(records, schema):
    by_day = defaultdict(list)
    for r in records:
        by_day[datetime.fromisoformat(r["event_time"]).date()].append(r["values"]["temperature"])
    days = sorted(by_day)
    return days, {d: schema.bin_counts(by_day[d]) for d in days}, by_day


def test_end_to_end_mean_shift_caught_with_no_false_alarms():
    start = datetime(2024, 6, 10)
    drift_start, drift_end = datetime(2024, 6, 27), datetime(2024, 6, 30)  # a 3-day +4C drift
    sim = Simulator(
        instrument_id="TEMP-001", start=start, end=start + timedelta(days=28),
        sampling_per_hour=60, seed=11,
        drift_windows=[DriftWindow(drift_start, drift_end, FaultKind.MEAN_SHIFT, 4.0)],
    )
    records, ground_truth = sim.run()

    cutoff = start + timedelta(days=14)  # first 14 days are clean
    clean_vals = [r["values"]["temperature"] for r in records
                  if datetime.fromisoformat(r["event_time"]) < cutoff]
    schema = _schema(clean_vals, bins=48)

    days, day_counts, _ = _build_days(records, schema)
    detector = DriftDetector.calibrate(schema, [day_counts[d] for d in days[:14]], k=8.0)

    tp = fp = fn = tn = 0
    for d in days[14:]:
        flagged = detector.is_drift(day_counts[d])
        truth = drift_start.date() <= d < drift_end.date()
        tp += flagged and truth
        fp += flagged and not truth
        fn += (not flagged) and truth
        tn += (not flagged) and not truth

    assert tp == 3 and fn == 0      # caught every injected drift day (recall)
    assert fp == 0                  # and cried wolf on none of the quiet days (precision)
    assert tn >= 10
    # the ground-truth log is what made this measurable, not eyeballed
    assert any(e.kind == FaultKind.MEAN_SHIFT.value for e in ground_truth)


def test_variance_drift_is_subtle_in_wasserstein_but_clear_in_the_moment():
    """Honest complement: daily Wasserstein under-detects a pure variance change; the variance moment
    (from power sums) catches it directly — why ADR-005 keeps the fingerprint as a second opinion."""
    start = datetime(2024, 6, 10)
    drift_start, drift_end = datetime(2024, 6, 27), datetime(2024, 6, 30)
    sim = Simulator(
        instrument_id="TEMP-001", start=start, end=start + timedelta(days=28),
        sampling_per_hour=60, seed=11,
        drift_windows=[DriftWindow(drift_start, drift_end, FaultKind.VARIANCE_INFLATION, 3.0)],
    )
    records, _ = sim.run()
    _, _, by_day = _build_days(records, _schema(
        [r["values"]["temperature"] for r in records
         if datetime.fromisoformat(r["event_time"]) < start + timedelta(days=14)]))

    days = sorted(by_day)
    var = {d: PowerSums.from_values(by_day[d]).variance for d in days}
    clean_var = float(np.median([var[d] for d in days[:14]]))
    drift_var = float(np.median([var[d] for d in days
                                 if drift_start.date() <= d < drift_end.date()]))
    assert drift_var > clean_var * 1.4    # the dispersion signal lives in the variance moment
