"""Tests for moments (power sums), percentiles, entropy, and the fingerprint (ADR-006).

These encode what the revised ADR-006 promises:
- moments from power sums are EXACT (match the values' true moments) — the fix that the binned
  midpoint method failed to achieve;
- power sums are additive (combining windows = adding sums);
- percentiles read from equal-mass bins are accurate, including the tails;
- entropy is maximal for a uniform spread and drops as the distribution concentrates;
- the fingerprint vector has the canonical shape;
- end-to-end: moments computed from the bitemporal fact's power sums are exact and reproducible.
"""
from datetime import datetime, timedelta

import numpy as np
import pytest

from binmoments.binning import derive_bin_schema
from binmoments.stats import (
    PowerSums,
    assemble_fingerprint,
    entropy_from_bins,
    percentiles_from_bins,
)


def _ref_moments(x):
    """Reference moments computed directly from the raw values (numpy)."""
    x = np.asarray(x, float)
    mu = x.mean()
    m2 = ((x - mu) ** 2).mean()
    m3 = ((x - mu) ** 3).mean()
    m4 = ((x - mu) ** 4).mean()
    skew = m3 / m2 ** 1.5
    kurt_excess = m4 / m2 ** 2 - 3.0
    return mu, m2, skew, kurt_excess


def test_power_sum_moments_are_exact():
    rng = np.random.default_rng(0)
    x = rng.normal(21.0, 3.0, 500_000)
    ps = PowerSums.from_values(x)
    mu, var, skew, kurt = _ref_moments(x)
    assert ps.mean == pytest.approx(mu, rel=1e-9)
    assert ps.variance == pytest.approx(var, rel=1e-6)
    assert ps.skewness == pytest.approx(skew, abs=1e-4)
    assert ps.kurtosis_excess == pytest.approx(kurt, abs=1e-4)


def test_power_sum_variance_beats_binned_midpoint():
    """The whole reason for ADR-006's reversal: power sums are exact where midpoints are biased."""
    rng = np.random.default_rng(1)
    x = rng.normal(21.0, 3.0, 1_000_000)
    true_var = float(np.var(x))

    ps = PowerSums.from_values(x)

    schema = derive_bin_schema(x, scope="x", channel="t", target_bin_count=32,
                               fit_start="a", fit_end="b", created_at="c")
    edges = np.asarray(schema.edges)
    mids = (edges[:-1] + edges[1:]) / 2
    counts = schema.bin_counts(x)
    c = np.array([counts.get(i, 0) for i in range(1, schema.interior_bin_count + 1)], float)
    p = c / c.sum()
    mean_mid = np.sum(p * mids)
    midpoint_var = float(np.sum(p * (mids - mean_mid) ** 2))

    assert ps.variance == pytest.approx(true_var, rel=1e-6)           # exact
    assert abs(ps.variance - true_var) < abs(midpoint_var - true_var)  # better than midpoint
    assert midpoint_var > true_var * 1.05                              # midpoint is biased high


def test_skewness_sign_and_kurtosis():
    rng = np.random.default_rng(2)
    normal = PowerSums.from_values(rng.normal(0, 1, 400_000))
    assert normal.skewness == pytest.approx(0.0, abs=0.02)
    assert normal.kurtosis_excess == pytest.approx(0.0, abs=0.05)

    right_skew = PowerSums.from_values(rng.exponential(1.0, 400_000))
    assert right_skew.skewness > 1.0           # exponential is strongly right-skewed
    assert right_skew.kurtosis_excess > 1.0    # and heavy-tailed


def test_power_sums_are_additive():
    rng = np.random.default_rng(3)
    a = rng.normal(20, 2, 10_000)
    b = rng.normal(25, 4, 7_000)
    combined = PowerSums.from_values(a) + PowerSums.from_values(b)
    direct = PowerSums.from_values(np.concatenate([a, b]))
    assert combined.mean == pytest.approx(direct.mean, rel=1e-12)
    assert combined.variance == pytest.approx(direct.variance, rel=1e-9)
    assert combined.n == direct.n


def test_percentiles_from_bins_accurate():
    rng = np.random.default_rng(4)
    x = rng.normal(21.0, 3.0, 1_000_000)
    schema = derive_bin_schema(x, scope="x", channel="t", target_bin_count=128,
                               fit_start="a", fit_end="b", created_at="c")
    counts = schema.bin_counts(x)
    pct = percentiles_from_bins(schema, counts, [0.5, 0.9, 0.95, 0.99])
    assert pct[0.5] == pytest.approx(21.0, abs=0.1)
    assert pct[0.95] == pytest.approx(21.0 + 1.645 * 3.0, abs=0.2)   # normal 95th percentile
    assert pct[0.5] < pct[0.9] < pct[0.95] < pct[0.99]               # monotonic


def test_entropy_uniform_high_concentrated_low():
    rng = np.random.default_rng(5)
    wide = rng.normal(21.0, 3.0, 500_000)
    schema = derive_bin_schema(wide, scope="x", channel="t", target_bin_count=32,
                               fit_start="a", fit_end="b", created_at="c")

    # The fitting data, re-binned, is ~uniform over bins -> near-maximal normalized entropy.
    _, h_wide = entropy_from_bins(schema.bin_counts(wide), schema.interior_bin_count)
    # A concentrated subset (narrow band) occupies fewer bins -> lower entropy.
    narrow = rng.normal(21.0, 0.4, 500_000)
    _, h_narrow = entropy_from_bins(schema.bin_counts(narrow), schema.interior_bin_count)

    assert h_wide > 0.95
    assert h_narrow < h_wide


def test_fingerprint_vector_shape_and_order():
    rng = np.random.default_rng(6)
    x = rng.normal(21.0, 3.0, 200_000)
    schema = derive_bin_schema(x, scope="x", channel="temperature", target_bin_count=64,
                               fit_start="a", fit_end="b", created_at="c")
    fp = assemble_fingerprint(PowerSums.from_values(x), schema.bin_counts(x), schema)
    v = fp.vector()
    assert len(v) == 9
    assert v[0] == fp.mean and v[1] == fp.variance and v[8] == fp.entropy_normalized


def test_end_to_end_fact_power_sums_exact_and_reproducible():
    from binmoments.simulator import Simulator
    from binmoments.fact import IncrementFact

    sim = Simulator(instrument_id="TEMP-001", start=datetime(2024, 1, 1),
                    end=datetime(2024, 1, 8), sampling_per_hour=4, seed=3)
    records, _ = sim.run()
    values = [r["values"]["temperature"] for r in records]
    schema = derive_bin_schema(values, scope="instrument:TEMP-001", channel="temperature",
                               target_bin_count=32, fit_start="a", fit_end="b", created_at="c")

    fact = IncrementFact()
    fact.ingest_records(records, schema)

    ps = fact.power_sums_current(instrument_id="TEMP-001", channel="temperature")
    ref = PowerSums.from_values(values)
    assert ps.mean == pytest.approx(ref.mean, rel=1e-9)
    assert ps.variance == pytest.approx(ref.variance, rel=1e-9)

    # As-of the future, the power sums equal the full set; the moments are exact, not binned.
    full = fact.power_sums_as_of(datetime(2030, 1, 1), instrument_id="TEMP-001", channel="temperature")
    assert full.mean == pytest.approx(ref.mean, rel=1e-9)
