"""Fault specifications and the ground-truth log (ADR-008).

Every fault the simulator injects is also emitted as a GroundTruthEvent, so detection by the
analytical core (drift, ADR-005; overflow/anomaly, ADR-002) can be SCORED against what was
actually injected — precision/recall, not eyeballing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class FaultKind(str, Enum):
    """The kinds of fault the slice simulator can inject."""

    MEAN_SHIFT = "mean_shift"                  # distribution shifts by a fixed offset (degrees)
    VARIANCE_INFLATION = "variance_inflation"  # noise spread multiplied by a factor
    STUCK = "stuck"                            # sensor returns a frozen constant
    SPIKE = "spike"                            # a single out-of-range excursion (exercises overflow)


@dataclass(frozen=True)
class DriftWindow:
    """A drift fault active over [start, end): a mean shift or a variance inflation."""

    start: datetime
    end: datetime
    kind: FaultKind        # MEAN_SHIFT or VARIANCE_INFLATION
    magnitude: float       # degrees for MEAN_SHIFT; multiplicative factor for VARIANCE_INFLATION


@dataclass(frozen=True)
class StuckWindow:
    """A stuck-sensor fault: a frozen constant reading over [start, end)."""

    start: datetime
    end: datetime
    value: float


@dataclass(frozen=True)
class Spike:
    """A single anomalous excursion at (or nearest to) ``at`` with absolute ``value``."""

    at: datetime
    value: float


@dataclass(frozen=True)
class GroundTruthEvent:
    """A record of one injected fault, for scoring detection."""

    kind: str
    start: datetime
    end: Optional[datetime]
    detail: dict

    def to_dict(self) -> dict:
        """JSON-serializable form (datetimes as ISO-8601)."""
        return {
            "kind": self.kind,
            "start": self.start.isoformat(),
            "end": self.end.isoformat() if self.end is not None else None,
            "detail": self.detail,
        }
