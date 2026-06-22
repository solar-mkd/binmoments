"""Distribution-shape statistics read from the bins: percentiles and entropy (ADR-002, ADR-006).

These are the statistics the equal-mass bins are *good* at. Percentiles are positional — they ask
"what value sits at this rank" — and are read off the cumulative counts; equal-mass bins keep the
tail bins populated, so p95/p99 are well resolved. Entropy is a shape statistic over the bin
proportions, with a clean interpretation under the equal-mass schema (the historical reference is
uniform, i.e. maximum entropy, so concentration shows up as an entropy drop).
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, Tuple

import numpy as np

from ..binning.schema import BinSchema


def percentiles_from_bins(
    schema: BinSchema,
    counts: Dict[int, int],
    quantiles: Iterable[float],
) -> Dict[float, float]:
    """Interpolated percentiles from the cumulative bin counts (ADR-002).

    Underflow/overflow mass is counted positionally (it sits below the min / above the max), so a
    quantile that falls into them is reported at the range boundary; for in-range data the value is
    linearly interpolated within the containing bin.
    """
    edges = np.asarray(schema.edges, dtype=float)
    k = schema.interior_bin_count
    interior = np.array([counts.get(i, 0) for i in range(1, k + 1)], dtype=float)
    under = float(counts.get(0, 0))
    over = float(counts.get(k + 1, 0))
    n_total = interior.sum() + under + over

    out: Dict[float, float] = {}
    for q in quantiles:
        out[q] = _one(edges, interior, under, over, n_total, q)
    return out


def _one(edges, interior, under, over, n_total, q) -> float:
    if n_total <= 0:
        return float("nan")
    target = q * n_total
    if target <= under:
        return float(edges[0])           # at or below the historical minimum
    cum = under
    for i in range(len(interior)):
        c = interior[i]
        if c > 0 and target <= cum + c:
            frac = (target - cum) / c
            return float(edges[i] + frac * (edges[i + 1] - edges[i]))
        cum += c
    return float(edges[-1])              # falls into overflow: at or above the historical maximum


def entropy_from_bins(counts: Dict[int, int], interior_bin_count: int) -> Tuple[float, float]:
    """Shannon entropy of the interior bin proportions: (entropy_nats, entropy_normalized).

    Normalized by ln(K) so 1.0 means a uniform spread across bins (the equal-mass reference's
    maximum-entropy state) and lower values mean the distribution has concentrated (ADR-006).
    """
    k = interior_bin_count
    c = np.array([counts.get(i, 0) for i in range(1, k + 1)], dtype=float)
    total = c.sum()
    if total <= 0:
        return 0.0, 0.0
    p = c / total
    nz = p[p > 0]
    h = float(-np.sum(nz * np.log(nz)))
    h_norm = float(h / math.log(k)) if k > 1 else 0.0
    return h, h_norm
