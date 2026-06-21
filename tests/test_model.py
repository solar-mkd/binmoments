"""Tests for the measurement & channel model (ADR-001).

These encode what ADR-001 promises:
- a scalar (rank-0) channel yields its value as the magnitude, with no direction;
- a vector (rank-1) channel yields its length as magnitude and a unit vector as direction;
- a zero vector has an undefined direction;
- the linear/circular flag is carried and validated;
- rank-2 is fenced (designed-for, ADR-015) and raises rather than guessing an implementation;
- ranks outside 0..2 are rejected (rank >= 3 is a non-goal).
"""
from datetime import datetime, timezone

import pytest

from binmoments.model import (
    Channel,
    ChannelKind,
    Measurement,
    decompose,
)


def test_scalar_channel_magnitude_is_value():
    ch = Channel(name="temperature", rank=0, kind=ChannelKind.LINEAR, unit="celsius")
    d = decompose(ch, 21.5)
    assert d.magnitude == 21.5
    assert d.direction is None


def test_linear_circular_flag_carried():
    linear = Channel("temperature", 0, ChannelKind.LINEAR, "celsius")
    circular = Channel("bearing", 0, ChannelKind.CIRCULAR, "degree")
    assert linear.kind is ChannelKind.LINEAR
    assert circular.kind is ChannelKind.CIRCULAR


def test_vector_channel_magnitude_and_unit_direction():
    ch = Channel(name="wind", rank=1, kind=ChannelKind.LINEAR, unit="m/s")
    d = decompose(ch, [3.0, 4.0])  # classic 3-4-5 triangle
    assert d.magnitude == pytest.approx(5.0)
    assert d.direction == pytest.approx([0.6, 0.8])


def test_zero_vector_has_undefined_direction():
    ch = Channel(name="wind", rank=1, kind=ChannelKind.LINEAR, unit="m/s")
    d = decompose(ch, [0.0, 0.0])
    assert d.magnitude == 0.0
    assert d.direction is None


def test_rank2_is_fenced_designed_for():
    ch = Channel(name="conductivity", rank=2, kind=ChannelKind.LINEAR, unit="S/m")
    with pytest.raises(NotImplementedError) as exc:
        decompose(ch, [[1.0, 0.0], [0.0, 1.0]])
    assert "ADR-015" in str(exc.value)


def test_rank_out_of_scope_rejected():
    with pytest.raises(ValueError):
        Channel(name="weird", rank=3, kind=ChannelKind.LINEAR, unit="x")


def test_measurement_requires_core_fields():
    now = datetime.now(timezone.utc)
    m = Measurement(instrument_id="TEMP-001", event_time=now, values={"temperature": 21.5})
    assert m.instrument_id == "TEMP-001"
    assert m.measurement_id is None

    with pytest.raises(ValueError):
        Measurement(instrument_id="", event_time=now, values={"temperature": 21.5})
    with pytest.raises(ValueError):
        Measurement(instrument_id="X", event_time=now, values={})
