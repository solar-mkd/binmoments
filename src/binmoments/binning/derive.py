"""The bin derivation method (ADR-002).

Derives a BinSchema from at least a year of historical values for one channel:

- **Edges** come from the empirical quantiles of the value distribution, so each interior bin holds
  roughly equal probability mass. Resolution follows the data — fine where readings concentrate,
  coarse in the sparse tails — which is what gives good tail percentiles and a clean overflow signal.
- **Bin count** is governed by the measurement density per comparison window, not the value range:
  resolution only pays off where there are enough counts to fill it (``recommend_bin_count``).
- The outermost edges are anchored to the **observed historical min/max**; overflow/underflow bins
  capture anything beyond, so a reading outside a year of observation is flagged as novel (ADR-002).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

import numpy as np

from .schema import BinSchema, compute_schema_id


def recommend_bin_count(
    window_measurement_count: int,
    *,
    min_per_bin: int = 20,
    min_bins: int = 8,
    max_bins: int = 256,
) -> int:
    """Recommend a bin count from the size of the smallest comparison window (ADR-002).

    The binding constraint on resolution is statistical, not computational: more bins means fewer
    counts per bin and a noisier histogram. ``min_per_bin`` keeps each bin's count high enough to be
    stable; the result is clamped to a sane range. Thin per-hour windows therefore get few bins and
    are compared only in their denser aggregated horizons (ADR-002/ADR-004).
    """
    if window_measurement_count <= 0:
        return min_bins
    raw = window_measurement_count // min_per_bin
    return int(max(min_bins, min(max_bins, raw)))


def derive_bin_schema(
    sample: Iterable[float],
    *,
    scope: str,
    channel: str,
    target_bin_count: int,
    fit_start: str,
    fit_end: str,
    created_at: Optional[str] = None,
) -> BinSchema:
    """Derive a frozen BinSchema from a historical sample (>= 1 year of values) for one channel.

    ``target_bin_count`` is the desired number of interior bins; ties in the data (e.g. a heavy
    point mass) can collapse adjacent equal-mass edges and yield fewer — zero-inflated channels are
    a deliberately deferred case (ADR-019), but the dedupe here keeps derivation robust regardless.
    """
    arr = np.asarray(list(sample), dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size < target_bin_count:
        raise ValueError(
            f"sample has {arr.size} values but {target_bin_count} bins were requested; "
            f"need at least one value per bin to place equal-mass edges (ADR-002)."
        )

    # Equal-mass interior edges from quantiles; dedupe to keep edges strictly increasing.
    quantiles = np.linspace(0.0, 1.0, target_bin_count + 1)
    edges = np.quantile(arr, quantiles)
    edges = np.unique(np.round(edges, 9))
    if edges.size < 2:
        raise ValueError(
            f"channel '{channel}': the sample is effectively constant; cannot place bins (ADR-002)."
        )

    edges_tuple = tuple(float(e) for e in edges)
    schema_id = compute_schema_id(scope, channel, edges_tuple, fit_start, fit_end)
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()

    return BinSchema(
        schema_id=schema_id,
        scope=scope,
        channel=channel,
        edges=edges_tuple,
        fit_start=fit_start,
        fit_end=fit_end,
        created_at=created_at,
    )
