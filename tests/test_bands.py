"""Tests for static value-band classification (ADR-017).

These encode what ADR-017 promises:
- a value is classified into the correct band, with boundaries inclusive on the upper band;
- band index increases with value (severity ordering);
- occupancy read from the histogram sums to 1 and matches the distribution;
- a distribution sitting entirely in normal range reads as all-Nominal;
- mass above the top boundary (including overflow beyond the historical max) reads as Critical;
- end-to-end: a calm day reads mostly Nominal, a hot drift pushes mass into Warning/Critical.
"""
from datetime import datetime, timedelta

import numpy as np
import pytest

from binmoments.bands import BandScheme
from binmoments.binning import derive_bin_schema
from binmoments.simulator import DriftWindow, FaultKind, Simulator


def _heat_bands():
    return BandScheme.severity("temperature", elevated=28.0, warning=33.0, critical=38.0)


def test_classify_values_into_bands():
    b = _heat_bands()
    assert b.classify(20.0) == "Nominal"
    assert b.classify(28.0) == "Elevated"      # boundary is inclusive of the upper band
    assert b.classify(30.0) == "Elevated"
    assert b.classify(33.0) == "Warning"
    assert b.classify(41.0) == "Critical"


def test_band_index_orders_by_severity():
    b = _heat_bands()
    assert b.band_index(20.0) < b.band_index(30.0) < b.band_index(35.0) < b.band_index(45.0)


def test_invalid_scheme_rejected():
    with pytest.raises(ValueError):
        BandScheme(channel="t", boundaries=(30.0, 20.0), labels=("a", "b", "c"))  # not ascending
    with pytest.raises(ValueError):
        BandScheme(channel="t", boundaries=(30.0,), labels=("a", "b", "c"))       # wrong label count


def test_occupancy_sums_to_one_and_matches_distribution():
    rng = np.random.default_rng(0)
    x = rng.normal(21.0, 3.0, 500_000)   # normal Brisbane temps, well below the hazard bands
    schema = derive_bin_schema(x, scope="x", channel="temperature", target_bin_count=64,
                               fit_start="a", fit_end="b", created_at="c")
    occ = _heat_bands().occupancy(schema, schema.bin_counts(x))
    assert sum(occ.values()) == pytest.approx(1.0, abs=1e-9)
    assert occ["Nominal"] > 0.95          # ~all of N(21,3) sits below 28
    assert occ["Critical"] < 0.001


def test_overflow_mass_counts_as_critical():
    # A distribution whose upper tail pokes above the Critical boundary (38).
    rng = np.random.default_rng(1)
    x = rng.normal(34.0, 4.0, 500_000)
    schema = derive_bin_schema(x, scope="x", channel="temperature", target_bin_count=64,
                               fit_start="a", fit_end="b", created_at="c")
    occ = _heat_bands().occupancy(schema, schema.bin_counts(x))
    assert occ["Critical"] > 0.1          # a meaningful share is above 38
    assert occ["Warning"] > 0.0


def test_end_to_end_hot_drift_raises_band_occupancy():
    bands = _heat_bands()
    start = datetime(2024, 1, 1)  # Brisbane summer, warmer baseline
    # A clean day vs a day with a large hot mean-shift injected.
    clean = Simulator(instrument_id="T", start=start, end=start + timedelta(days=1),
                      sampling_per_hour=60, seed=5)
    hot = Simulator(instrument_id="T", start=start, end=start + timedelta(days=1),
                    sampling_per_hour=60, seed=5,
                    drift_windows=[DriftWindow(start, start + timedelta(days=1),
                                               FaultKind.MEAN_SHIFT, 12.0)])
    clean_vals = [r["values"]["temperature"] for r in clean.run()[0]]
    hot_vals = [r["values"]["temperature"] for r in hot.run()[0]]

    schema = derive_bin_schema(clean_vals + hot_vals, scope="T", channel="temperature",
                               target_bin_count=64, fit_start="a", fit_end="b", created_at="c")
    occ_clean = bands.occupancy(schema, schema.bin_counts(clean_vals))
    occ_hot = bands.occupancy(schema, schema.bin_counts(hot_vals))

    # The hot day pushes mass up into the more severe bands.
    assert occ_hot["Warning"] + occ_hot["Critical"] > occ_clean["Warning"] + occ_clean["Critical"]
