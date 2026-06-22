"""The bitemporal increment row (ADR-004).

Every count in the system is recorded as an append-only, signed delta to one bin, tagged with two
times: the *valid time* (``event_hour`` — the hour the measurement is about) and the *transaction
time* (``arrival_time`` — when the system recorded it). Keeping both axes is what lets the system
answer "what did I know, and when did I know it." Rows are immutable; corrections and late data are
new rows, never edits.

Each row also carries the reading's raw ``value`` (ADR-004 decision 2a). From it the additive
power-sum deltas follow as ``delta * (1, x, x^2, x^3, x^4)``, so exact moments (ADR-006) ride the
same bitemporal rails as the bin counts: a measurement asserts a reading (delta +1), a correction
retracts the old reading (delta -1, old value) and asserts the new one (delta +1, new value).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class EntryType(str, Enum):
    """The nature of an increment row (audit/provenance; lateness is computed, not labelled)."""

    MEASUREMENT = "measurement"  # an ingested reading (on-time or late — lateness is a filter, ADR-004)
    CORRECTION = "correction"    # a compensating delta restating a previous reading


@dataclass(frozen=True)
class IncrementRow:
    """One append-only signed delta — a reading asserted (+1) or retracted (-1) — with both times.

    The row carries everything needed for BOTH the bin counts (``bin`` + ``delta``) and the exact
    moments (``value`` + ``delta``), so the two statistics stay perfectly in sync (ADR-004/006).
    """

    instrument_id: str
    channel: str
    bin_schema_id: str
    bin: int
    event_hour: datetime          # valid time: the hour the measurement is about
    arrival_time: datetime        # transaction time: when the system recorded this row
    delta: int                    # +1 asserts a reading, -1 retracts it (corrections do both)
    value: float                  # the reading's raw value; powers follow as delta * value**k
    entry_type: EntryType = EntryType.MEASUREMENT
    measurement_id: Optional[str] = None  # provenance / correction anchor (ADR-009 holds identity)
