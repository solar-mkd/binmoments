"""Materialized current-state histogram.

The increment fact (ADR-004) stores every change as an append-only, signed
delta keyed by (instrument, bin_schema, event_hour, bin), timestamped with both
valid time (event_hour) and transaction time (arrival_time). Reading the
"current" histogram from it means summing all deltas known so far for each
(instrument, schema, event_hour, bin) key -- which, at millions of rows, is
wasteful to do on every read.

This module maintains that sum as a materialized table: the *current state*,
i.e. the fact with transaction time collapsed (all known deltas applied,
including late corrections, per ADR-020 option A). It supports two equivalent
ways to build it:

  * incremental:  apply each arriving batch of deltas to the running state
  * rebuild:      apply every delta in the fact from scratch

These two MUST agree, because bin counts are additive and addition is
associative and commutative (a commutative monoid -- see the mathematical
companion). That equality is the correctness guarantee that keeps the
materialized table a trustworthy cache: it can always be rebuilt from the
immutable fact, so it can never become a corrupted source of truth.

The object stores *only* the histogram (bin counts). The analogous current
state for the power sums (fast moments) is the identical pattern and is left
as a recorded extension (ADR-020).
"""

from __future__ import annotations

from typing import Dict, Iterable, Iterator, Tuple

# (instrument_id, bin_schema_id, event_hour, bin_index)
BinKey = Tuple[str, str, str, int]


class CurrentStateHistogram:
    """A derived, rebuildable projection of the increment fact's bin counts.

    Holds a sparse map from bin key to net count. A bin whose net count returns
    to zero is dropped, so the state stays sparse and a rebuild and an
    incremental maintenance of the same deltas produce identical maps.
    """

    def __init__(self) -> None:
        self._counts: Dict[BinKey, float] = {}

    # -- maintenance -------------------------------------------------------

    def apply(self, key: BinKey, delta: float) -> "CurrentStateHistogram":
        """Apply a single signed delta to one bin. Dropping zeroed bins keeps
        the projection sparse and rebuild-equivalent."""
        new = self._counts.get(key, 0.0) + delta
        if new == 0:
            self._counts.pop(key, None)
        else:
            self._counts[key] = new
        return self

    def apply_many(self, items: Iterable[Tuple[BinKey, float]]) -> "CurrentStateHistogram":
        """Apply a batch of (key, delta) pairs -- the incremental path used as
        each new batch of increments arrives."""
        for key, delta in items:
            self.apply(key, delta)
        return self

    def merge(self, other: "CurrentStateHistogram") -> "CurrentStateHistogram":
        """Fold another current-state into this one (the additive merge).
        Combining two states is just adding their counts."""
        return self.apply_many(other._counts.items())

    @classmethod
    def rebuild(cls, items: Iterable[Tuple[BinKey, float]]) -> "CurrentStateHistogram":
        """Build the current state from scratch by applying every delta in the
        fact. This is the safety net / disaster-recovery path: the materialized
        table is correct iff it equals this."""
        return cls().apply_many(items)

    # -- reads -------------------------------------------------------------

    @property
    def counts(self) -> Dict[BinKey, float]:
        """The full (already sparse) map of bin key -> net count."""
        return dict(self._counts)

    def histogram(self, instrument_id: str, bin_schema_id: str) -> Dict[Tuple[str, int], float]:
        """Fast read: the current histogram for one instrument/schema as
        {(event_hour, bin_index): count}. This is the read the materialized
        table exists to make cheap -- no delta replay."""
        out: Dict[Tuple[str, int], float] = {}
        for (inst, schema, hour, b), c in self._counts.items():
            if inst == instrument_id and schema == bin_schema_id:
                out[(hour, b)] = c
        return out

    def bin_totals(self, instrument_id: str, bin_schema_id: str) -> Dict[int, float]:
        """The current distribution for one instrument/schema, summed over all
        hours: {bin_index: total_count}. An arbitrary-window total is the same
        sum restricted to the hours in the window."""
        out: Dict[int, float] = {}
        for (inst, schema, _hour, b), c in self._counts.items():
            if inst == instrument_id and schema == bin_schema_id:
                out[b] = out.get(b, 0.0) + c
        return out

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CurrentStateHistogram):
            return NotImplemented
        return self._counts == other._counts

    def __len__(self) -> int:
        return len(self._counts)

    def __repr__(self) -> str:
        return f"CurrentStateHistogram(bins={len(self._counts)})"


def increments_to_items(
    rows: Iterable[object],
    *,
    instrument_attr: str = "instrument_id",
    schema_attr: str = "bin_schema_id",
    hour_attr: str = "event_hour",
    bin_attr: str = "bin_index",
    delta_attr: str = "count_delta",
) -> Iterator[Tuple[BinKey, float]]:
    """Adapt increment-fact rows into (key, delta) pairs for the maintenance
    methods above.

    Field names default to the increment-fact schema but are overridable, so
    this stays decoupled from the exact IncrementRow definition. Each row is
    expected to carry the bin it was assigned to (binning happens upstream in
    the package); this projection only sums the signed count deltas.
    """
    for r in rows:
        key: BinKey = (
            getattr(r, instrument_attr),
            getattr(r, schema_attr),
            getattr(r, hour_attr),
            getattr(r, bin_attr),
        )
        yield key, float(getattr(r, delta_attr))
