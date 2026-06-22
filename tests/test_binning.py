"""Tests for bin schema derivation and the frozen artifact (ADR-002, ADR-003).

These encode what the ADRs promise:
- equal mass: on the fitting sample, interior bins hold ~equal counts (ADR-002 core property);
- variable width: bins are narrow where data concentrates, wide in the sparse tails (ADR-002);
- overflow/underflow: values beyond the historical range are flagged as novel (ADR-002);
- frozen, content-derived id: same data -> same schema_id; different data -> different id (ADR-003);
- the value-axis transform is the frozen min/max map (ADR-002);
- recommend_bin_count follows the measurement-density rule and clamps (ADR-002);
- end-to-end with the simulator: a year of temperature derives a schema; an injected spike lands
  in overflow.
"""
import numpy as np
import pytest

from binmoments.binning import (
    BinSchema,
    derive_bin_schema,
    recommend_bin_count,
)


def _normal_sample(n=100_000, mean=21.0, std=3.0, seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(mean, std, n)


def _schema(sample, bins=50):
    return derive_bin_schema(
        sample,
        scope="instrument:TEST-001",
        channel="temperature",
        target_bin_count=bins,
        fit_start="2024-01-01T00:00:00",
        fit_end="2025-01-01T00:00:00",
        created_at="2025-01-01T00:00:00",
    )


def test_equal_mass_on_fitting_sample():
    sample = _normal_sample()
    schema = _schema(sample, bins=50)
    counts = schema.bin_counts(sample)
    interior = [counts.get(i, 0) for i in range(1, schema.interior_bin_count + 1)]
    expected = len(sample) / schema.interior_bin_count
    # Quantile bins give near-equal mass; allow a modest tolerance.
    assert max(interior) < expected * 1.15
    assert min(interior) > expected * 0.85


def test_variable_width_narrow_in_the_middle():
    sample = _normal_sample()
    schema = _schema(sample, bins=50)
    widths = np.diff(np.asarray(schema.edges))
    n = len(widths)
    central = np.median(widths[n // 2 - 3 : n // 2 + 3])
    edge_widths = np.median(np.concatenate([widths[:3], widths[-3:]]))
    # A bell-shaped distribution is dense in the middle -> narrower central bins.
    assert central < edge_widths


def test_overflow_and_underflow_flag_novel_values():
    sample = _normal_sample()
    schema = _schema(sample)
    assert schema.assign(schema.value_min - 10.0) == 0                       # underflow
    assert schema.assign(schema.value_max + 10.0) == schema.interior_bin_count + 1  # overflow
    mid = float(np.median(sample))
    assert 1 <= schema.assign(mid) <= schema.interior_bin_count              # interior


def test_value_at_max_is_last_interior_not_overflow():
    sample = _normal_sample()
    schema = _schema(sample)
    assert schema.assign(schema.value_max) == schema.interior_bin_count


def test_schema_id_is_deterministic_and_data_sensitive():
    sample = _normal_sample(seed=1)
    a = _schema(sample)
    b = _schema(sample)
    assert a.schema_id == b.schema_id                       # same data + params -> same id

    shifted = _schema(_normal_sample(seed=1) + 5.0)
    assert shifted.schema_id != a.schema_id                 # different edges -> different id
    assert not a.compatible_with(shifted)                   # merge guard would refuse


def test_value_axis_transform_is_frozen_min_max_map():
    sample = _normal_sample()
    schema = _schema(sample)
    assert schema.normalize(schema.value_min) == pytest.approx(0.0)
    assert schema.normalize(schema.value_max) == pytest.approx(1.0)


def test_recommend_bin_count_rule_and_clamp():
    assert recommend_bin_count(0) == 8                       # floor
    assert recommend_bin_count(60, min_per_bin=20) == 8      # 60//20=3 -> clamped up to min_bins
    assert recommend_bin_count(10_000, min_per_bin=20) == 256  # clamped to max
    assert recommend_bin_count(2_000, min_per_bin=20) == 100   # 2000//20


def test_too_few_values_is_rejected():
    with pytest.raises(ValueError):
        _schema(np.array([1.0, 2.0, 3.0]), bins=50)


def test_end_to_end_simulator_spike_lands_in_overflow():
    from datetime import datetime
    from binmoments.simulator import Simulator

    sim = Simulator(
        instrument_id="TEMP-001",
        start=datetime(2024, 1, 1),
        end=datetime(2025, 1, 1),  # a full year
        sampling_per_hour=1,
        seed=3,
    )
    records, _ = sim.run()
    values = [r["values"]["temperature"] for r in records]

    schema = derive_bin_schema(
        values,
        scope="instrument:TEMP-001",
        channel="temperature",
        target_bin_count=64,
        fit_start="2024-01-01T00:00:00",
        fit_end="2025-01-01T00:00:00",
        created_at="2025-01-01T00:00:00",
    )
    # A 58 degC spike is far beyond a year of Brisbane temperature -> overflow (novelty).
    assert schema.assign(58.0) == schema.interior_bin_count + 1
    # A normal mid-range reading lands in the interior.
    assert 1 <= schema.assign(21.0) <= schema.interior_bin_count
