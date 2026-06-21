"""The measurement record (ADR-001, ADR-008).

A measurement carries the instrument it came from, the instant it is *about* (event time), its
per-channel raw values, and an optional ``measurement_id`` used as the anchor for corrections
(ADR-004). Values are raw here; reduction to scalar magnitudes happens via ``channel.decompose``
(ADR-001), downstream in the silver layer (ADR-009). The system-assigned ``arrival_time`` is NOT
part of the measurement — it is stamped at ingestion (ADR-004), keeping valid time (event) and
transaction time (arrival) cleanly separated.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class Measurement:
    """One reading from one instrument, about one instant, across one or more channels."""

    instrument_id: str
    event_time: datetime
    values: Mapping[str, Any]              # channel name -> raw value (scalar or vector)
    measurement_id: Optional[str] = None   # correction anchor (ADR-004)

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise ValueError("measurement requires a non-empty instrument_id.")
        if not isinstance(self.event_time, datetime):
            raise ValueError("measurement event_time must be a datetime.")
        if not self.values:
            raise ValueError("measurement requires at least one channel value.")
