"""Synthetic temperature simulator with ground-truth fault injection (ADR-008).

Produces a reproducible stream of JSON-serializable measurement records AND a ground-truth log of
every injected fault, so the analytical core (drift, ADR-005; overflow anomalies, ADR-002) can be
SCORED — not just run. Two determinism properties make the ground truth trustworthy:

  1. A given ``seed`` yields byte-identical output.
  2. A run WITH faults differs from a run WITHOUT them ONLY inside the injected fault windows —
     because faults are applied on top of the same drawn noise, never by redrawing it.

Scope (ADR-008 discipline): the slice generates ONE scalar channel (temperature) with injected
mean-shift drift, variance inflation, stuck-sensor, and spike anomalies. Late-arrival and correction
generation — which validate the bitemporal fact (ADR-004) — are added when that layer is built; the
record envelope already carries ``arrival_time`` so they slot in without reshaping.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Tuple

import numpy as np

from .faults import DriftWindow, FaultKind, GroundTruthEvent, Spike, StuckWindow
from .temperature_field import TemperatureField


@dataclass
class Simulator:
    """Generate a reproducible temperature stream with known, injected faults."""

    instrument_id: str
    start: datetime
    end: datetime
    sampling_per_hour: int = 60
    seed: int = 0
    channel: str = "temperature"
    field_model: TemperatureField = field(default_factory=TemperatureField)
    delivery_latency_seconds: int = 5

    drift_windows: List[DriftWindow] = field(default_factory=list)
    stuck_windows: List[StuckWindow] = field(default_factory=list)
    spikes: List[Spike] = field(default_factory=list)

    def _timestamps(self) -> List[datetime]:
        step = timedelta(seconds=3600.0 / self.sampling_per_hour)
        out: List[datetime] = []
        t = self.start
        while t < self.end:
            out.append(t)
            t += step
        return out

    def run(self) -> Tuple[List[dict], List[GroundTruthEvent]]:
        """Return (records, ground_truth). Records are JSON-serializable dicts."""
        rng = np.random.default_rng(self.seed)
        timestamps = self._timestamps()
        n = len(timestamps)
        noise = rng.normal(0.0, self.field_model.noise_std, n)
        half_step = (3600.0 / self.sampling_per_hour) / 2.0  # seconds, for spike matching

        records: List[dict] = []
        for i, when in enumerate(timestamps):
            value = self.field_model.deterministic(when)

            # Drift faults: mean shift adds; variance inflation scales the drawn noise.
            variance_factor = 1.0
            mean_offset = 0.0
            for w in self.drift_windows:
                if w.start <= when < w.end:
                    if w.kind is FaultKind.MEAN_SHIFT:
                        mean_offset += w.magnitude
                    elif w.kind is FaultKind.VARIANCE_INFLATION:
                        variance_factor *= w.magnitude
            value = value + noise[i] * variance_factor + mean_offset

            # Stuck-sensor faults override the value with a frozen constant.
            for s in self.stuck_windows:
                if s.start <= when < s.end:
                    value = s.value

            # Spikes override the value at the nearest reading.
            for sp in self.spikes:
                if abs((sp.at - when).total_seconds()) < half_step:
                    value = sp.value

            arrival = when + timedelta(seconds=self.delivery_latency_seconds)
            records.append(
                {
                    "instrument_id": self.instrument_id,
                    "measurement_id": f"{self.instrument_id}-{i:08d}",
                    "event_time": when.isoformat(),
                    "arrival_time": arrival.isoformat(),
                    "values": {self.channel: round(float(value), 3)},
                }
            )

        return records, self._ground_truth()

    def _ground_truth(self) -> List[GroundTruthEvent]:
        events: List[GroundTruthEvent] = []
        for w in self.drift_windows:
            events.append(
                GroundTruthEvent(
                    kind=w.kind.value,
                    start=w.start,
                    end=w.end,
                    detail={"magnitude": w.magnitude, "channel": self.channel},
                )
            )
        for s in self.stuck_windows:
            events.append(
                GroundTruthEvent(
                    kind=FaultKind.STUCK.value,
                    start=s.start,
                    end=s.end,
                    detail={"value": s.value, "channel": self.channel},
                )
            )
        for sp in self.spikes:
            events.append(
                GroundTruthEvent(
                    kind=FaultKind.SPIKE.value,
                    start=sp.at,
                    end=None,
                    detail={"value": sp.value, "channel": self.channel},
                )
            )
        return events
