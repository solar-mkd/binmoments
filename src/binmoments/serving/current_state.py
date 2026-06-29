"""Materialized current-state histogram.

The increment fact (ADR-004) stores every change as an append-only, signed
delta keyed by (instrument, bin_schema, event_hour, bin). The *current-state*
histogram is that fact with both transaction time AND the hour dimension
collapsed: one net count per (instrument, bin_schema, bin) -- i.e. the
instrument's whole current distribution, summed over all hours and including
all known corrections (ADR-020 option A).

This is deliberately a different grain from the gold per-hour `histogram`
table: the per-hour histogram answers "what did the distribution look like in
each hour?" (time-resolved, you index straight to the hour); this current-state
answers "what is this instrument's distribution right now?" (collapsed, one fast
read), and exists so that the latest distribution is served without summing the
log on every read.

It supports two equivalent ways to build it:

  * incremental:  apply each arriving batch of deltas to the running state
  * rebuild:      apply every delta in the fact from scratch

These MUST agree, because bin counts are additive and addition is associative
and commutative (a commutative monoid -- see the mathematical companion). That
equality is the guarantee that keeps the materialized table a trustworthy cache:
it can always be rebuilt from the immutable fact, so it can never become a
corrupted source of truth.
"""

from __future__ import annotations

from typing import Dict, Iterable, Iterator, Tuple

# (instrument_id, bin_schema_id, bin_index) -- the hour dimension is collapsed
BinKey = Tuple[str, str, int]


class CurrentStateHistogram:
    """A derived, rebuildable projection of the fact's bin counts, collapsed to
    one net count per (instrument, schema, bin). Bins whose net count returns to
    zero are dropped, so a rebuild and an incremental maintenance of the same
    deltas produce identical maps."""

    def __init__(self) -> None:
        self._counts: Dict[BinKey, float] = {}

    # -- maintenance -------------------------------------------------------

    def apply(self, key: BinKey, delta: float) -> "CurrentStateHistogram":
        new = self._counts.get(key, 0.0) + delta
        if new == 0:
            self._counts.pop(key, None)
        else:
            self._counts[key] = new
        return self

    def apply_many(self, items: Iterable[Tuple[BinKey, float]]) -> "CurrentStateHistogram":
        for key, delta in items:
            self.apply(key, delta)
        return self

    def merge(self, other: "CurrentStateHistogram") -> "CurrentStateHistogram":
        return self.apply_many(other._counts.items())

    @classmethod
    def rebuild(cls, items: Iterable[Tuple[BinKey, float]]) -> "CurrentStateHistogram":
        """Build from scratch by applying every delta in the fact -- the
        disaster-recovery path the materialized table is checked against."""
        return cls().apply_many(items)

    # -- reads -------------------------------------------------------------

    @property
    def counts(self) -> Dict[BinKey, float]:
        return dict(self._counts)

    def distribution(self, instrument_id: str, bin_schema_id: str) -> Dict[int, float]:
        """Fast read: the current distribution for one instrument/schema as
        {bin_index: count}. This is the read the materialized table exists to
        make cheap -- no delta replay, no per-hour summation."""
        out: Dict[int, float] = {}
        for (inst, schema, b), c in self._counts.items():
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
    bin_attr: str = "bin_index",
    delta_attr: str = "count_delta",
) -> Iterator[Tuple[BinKey, float]]:
    """Adapt increment-fact rows into (key, delta) pairs at the collapsed grain.

    The event_hour on each row is intentionally ignored: the current-state
    histogram sums over all hours. Field names default to the increment-fact
    schema but are overridable, to stay decoupled from the exact IncrementRow.
    """
    for r in rows:
        key: BinKey = (
            getattr(r, instrument_attr),
            getattr(r, schema_attr),
            getattr(r, bin_attr),
        )
        yield key, float(getattr(r, delta_attr))
