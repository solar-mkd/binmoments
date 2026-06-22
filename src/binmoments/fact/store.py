"""The append-only bitemporal increment fact (ADR-004).

Reference implementation of the fact's *logic* — append, as-of reconstruction, horizon
materialization, and corrections — as pure Python over immutable rows. The same operations map onto
a Delta table and Spark SQL on Databricks (an as-of query is a ``WHERE arrival_time <= t`` filter, a
``GROUP BY``, and a ``SUM``). Keeping the logic storage-agnostic makes it fully testable locally and
keeps it clean (ADR-010: native where it pays, agnostic in the pure logic).

The fact carries two additive quantities on the same rows (ADR-004 decision 2a): **bin counts**
(``bin`` + ``delta``) for distribution shape, and **power sums** (``value`` + ``delta``) for exact
moments (ADR-006). Both obey identical append-only, as-of, horizon, and correction rules.

Guarantees: append-only (rows are never mutated/deleted); as-of reproducibility (sum the deltas that
had arrived by an instant); merge guard (counts never summed across different ``bin_schema_id``).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

from ..binning.schema import BinSchema
from ..stats.power_sums import PowerSums
from .increment import EntryType, IncrementRow


def floor_to_hour(when: datetime) -> datetime:
    """Truncate a timestamp to its hour — the valid-time granularity of the system."""
    return when.replace(minute=0, second=0, microsecond=0)


def measurement_increment(
    schema: BinSchema,
    *,
    instrument_id: str,
    channel: str,
    value: float,
    event_time: datetime,
    arrival_time: datetime,
    measurement_id: Optional[str] = None,
) -> IncrementRow:
    """Build a +1 measurement increment by binning ``value`` under ``schema`` (ADR-002/004)."""
    return IncrementRow(
        instrument_id=instrument_id,
        channel=channel,
        bin_schema_id=schema.schema_id,
        bin=schema.assign(value),
        event_hour=floor_to_hour(event_time),
        arrival_time=arrival_time,
        delta=1,
        value=float(value),
        entry_type=EntryType.MEASUREMENT,
        measurement_id=measurement_id,
    )


def _sum_deltas(rows: Iterable[IncrementRow]) -> Dict[int, int]:
    acc: Dict[int, int] = {}
    for r in rows:
        acc[r.bin] = acc.get(r.bin, 0) + r.delta
    return {b: c for b, c in acc.items() if c != 0}


def _sum_powers(rows: Iterable[IncrementRow]) -> PowerSums:
    n = s1 = s2 = s3 = s4 = 0.0
    for r in rows:
        d, x = r.delta, r.value
        n += d
        s1 += d * x
        s2 += d * x * x
        s3 += d * x * x * x
        s4 += d * x * x * x * x
    return PowerSums(n, s1, s2, s3, s4)


class IncrementFact:
    """An append-only store of bitemporal increment rows (ADR-004)."""

    def __init__(self) -> None:
        self._rows: List[IncrementRow] = []

    # --- writes (append-only) ---------------------------------------------------------------

    def append(self, row: IncrementRow) -> None:
        self._rows.append(row)

    def extend(self, rows: Iterable[IncrementRow]) -> None:
        self._rows.extend(rows)

    def ingest_records(self, records: Iterable[dict], schema: BinSchema) -> int:
        """Convert ingestion/simulator records into +1 measurement increments and append them.

        Each record carries instrument_id, ISO ``event_time`` and ``arrival_time``, and
        ``values[channel]``. Returns the number of rows appended.
        """
        added = 0
        for rec in records:
            value = rec["values"][schema.channel]
            self.append(
                measurement_increment(
                    schema,
                    instrument_id=rec["instrument_id"],
                    channel=schema.channel,
                    value=value,
                    event_time=datetime.fromisoformat(rec["event_time"]),
                    arrival_time=datetime.fromisoformat(rec["arrival_time"]),
                    measurement_id=rec.get("measurement_id"),
                )
            )
            added += 1
        return added

    def apply_correction(
        self,
        *,
        instrument_id: str,
        channel: str,
        bin_schema_id: str,
        event_hour: datetime,
        from_bin: int,
        to_bin: int,
        from_value: float,
        to_value: float,
        arrival_time: datetime,
        measurement_id: Optional[str] = None,
    ) -> None:
        """Restate a reading by retracting the old one (-1, old value) and asserting the new one
        (+1, new value), append-only (ADR-004). Both bin counts and power sums stay consistent."""
        common = dict(
            instrument_id=instrument_id,
            channel=channel,
            bin_schema_id=bin_schema_id,
            event_hour=floor_to_hour(event_hour),
            arrival_time=arrival_time,
            entry_type=EntryType.CORRECTION,
            measurement_id=measurement_id,
        )
        self.append(IncrementRow(bin=from_bin, delta=-1, value=float(from_value), **common))
        self.append(IncrementRow(bin=to_bin, delta=+1, value=float(to_value), **common))

    # --- reads ------------------------------------------------------------------------------

    def _select(
        self,
        *,
        instrument_id: str,
        channel: str,
        event_hour: Optional[datetime] = None,
        max_arrival: Optional[datetime] = None,
        bin_schema_id: Optional[str] = None,
    ) -> List[IncrementRow]:
        rows = [
            r for r in self._rows
            if r.instrument_id == instrument_id and r.channel == channel
        ]
        if event_hour is not None:
            eh = floor_to_hour(event_hour)
            rows = [r for r in rows if r.event_hour == eh]
        if bin_schema_id is not None:
            rows = [r for r in rows if r.bin_schema_id == bin_schema_id]
        else:
            present = {r.bin_schema_id for r in rows}
            if len(present) > 1:
                raise ValueError(
                    "query spans multiple bin_schema_id values; name one — counts are never "
                    "merged across schema versions (ADR-003)."
                )
        if max_arrival is not None:
            rows = [r for r in rows if r.arrival_time <= max_arrival]
        return rows

    def as_of(
        self,
        when: datetime,
        *,
        instrument_id: str,
        channel: str,
        event_hour: Optional[datetime] = None,
        bin_schema_id: Optional[str] = None,
    ) -> Dict[int, int]:
        """The bin histogram as it was known at transaction-time ``when`` (reproducibility)."""
        return _sum_deltas(
            self._select(instrument_id=instrument_id, channel=channel,
                         event_hour=event_hour, max_arrival=when, bin_schema_id=bin_schema_id)
        )

    def current(
        self,
        *,
        instrument_id: str,
        channel: str,
        event_hour: Optional[datetime] = None,
        bin_schema_id: Optional[str] = None,
    ) -> Dict[int, int]:
        """The latest known bin histogram (all arrivals included)."""
        return _sum_deltas(
            self._select(instrument_id=instrument_id, channel=channel,
                         event_hour=event_hour, bin_schema_id=bin_schema_id)
        )

    def power_sums_as_of(
        self,
        when: datetime,
        *,
        instrument_id: str,
        channel: str,
        event_hour: Optional[datetime] = None,
        bin_schema_id: Optional[str] = None,
    ) -> PowerSums:
        """Exact power sums as known at ``when`` — the basis for as-of-reproducible moments (ADR-006)."""
        return _sum_powers(
            self._select(instrument_id=instrument_id, channel=channel,
                         event_hour=event_hour, max_arrival=when, bin_schema_id=bin_schema_id)
        )

    def power_sums_current(
        self,
        *,
        instrument_id: str,
        channel: str,
        event_hour: Optional[datetime] = None,
        bin_schema_id: Optional[str] = None,
    ) -> PowerSums:
        """The latest known power sums (all arrivals included)."""
        return _sum_powers(
            self._select(instrument_id=instrument_id, channel=channel,
                         event_hour=event_hour, bin_schema_id=bin_schema_id)
        )

    def histogram_at_horizon(
        self,
        event_hour: datetime,
        horizon: Optional[timedelta],
        *,
        instrument_id: str,
        channel: str,
        bin_schema_id: Optional[str] = None,
    ) -> Dict[int, int]:
        """Bin histogram for one event-hour using only data within ``horizon`` of it (ADR-004).
        ``horizon=None`` means 'final' — all arrivals."""
        eh = floor_to_hour(event_hour)
        cutoff = datetime.max if horizon is None else eh + horizon
        return self.as_of(cutoff, instrument_id=instrument_id, channel=channel,
                          event_hour=eh, bin_schema_id=bin_schema_id)

    def event_hours(self, *, instrument_id: str, channel: str) -> List[datetime]:
        """Sorted distinct event-hours present for an instrument/channel."""
        return sorted(
            {r.event_hour for r in self._rows
             if r.instrument_id == instrument_id and r.channel == channel}
        )

    def changes_between(
        self,
        t1: datetime,
        t2: datetime,
        *,
        instrument_id: str,
        channel: str,
    ) -> List[IncrementRow]:
        """Rows learned in (t1, t2] — the new information that explains how the picture changed."""
        rows = [
            r for r in self._rows
            if r.instrument_id == instrument_id and r.channel == channel
            and t1 < r.arrival_time <= t2
        ]
        return sorted(rows, key=lambda r: r.arrival_time)

    @property
    def rows(self) -> tuple:
        """Read-only view of all rows (the fact is append-only)."""
        return tuple(self._rows)

    def __len__(self) -> int:
        return len(self._rows)
