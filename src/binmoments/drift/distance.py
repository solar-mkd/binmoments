"""Wasserstein-1 (earth-mover's) distance between two binned distributions (ADR-005).

Why Wasserstein and not cosine (ADR-005 rejects cosine): the earth-mover's distance measures the
*cost to move mass* from one distribution to the other, so it is sensitive to both a shift in level
and a change in shape, and — crucially — it is expressed in the value's own units. A pure shift of
5 degrees yields a distance of (about) 5, which is interpretable. Cosine similarity, treating the
histogram as a vector of bin heights, would conflate a shift with a shape change and lose the units.

Both distributions are resampled onto a single fixed value grid before comparing (ADR-016), so the
*same* code handles two histograms on the same schema and two on different schemas (e.g. across an
annual refit, where the bin edges have moved). The grid is built on the fly and nothing is stored.
"""
from __future__ import annotations

from typing import Dict

import numpy as np

from ..binning.schema import BinSchema


def wasserstein1(
    edges_a: np.ndarray,
    counts_a: np.ndarray,
    edges_b: np.ndarray,
    counts_b: np.ndarray,
    *,
    grid_points: int = 1024,
) -> float:
    """Wasserstein-1 distance between two interior histograms, in value units.

    ``edges_*`` are the K+1 interior edges; ``counts_*`` are the K interior counts. The result is the
    integral of the absolute difference of the two cumulative distributions over a shared grid.
    """
    ea = np.asarray(edges_a, dtype=float)
    eb = np.asarray(edges_b, dtype=float)
    ca = np.asarray(counts_a, dtype=float)
    cb = np.asarray(counts_b, dtype=float)
    if ca.sum() <= 0 or cb.sum() <= 0:
        return float("nan")

    # Cumulative proportion at each edge: 0 at the first edge, 1 at the last.
    cum_a = np.concatenate([[0.0], np.cumsum(ca / ca.sum())])
    cum_b = np.concatenate([[0.0], np.cumsum(cb / cb.sum())])

    lo = min(ea[0], eb[0])
    hi = max(ea[-1], eb[-1])
    if hi <= lo:
        return 0.0
    grid = np.linspace(lo, hi, grid_points)

    # Piecewise-linear CDFs evaluated on the shared grid (np.interp clamps to [0,1] outside range).
    cdf_a = np.interp(grid, ea, cum_a)
    cdf_b = np.interp(grid, eb, cum_b)
    diff = np.abs(cdf_a - cdf_b)
    # Trapezoidal integral over the grid (version-proof: np.trapz was removed in numpy 2.x).
    return float(np.sum((diff[:-1] + diff[1:]) / 2.0 * np.diff(grid)))


def _interior(schema: BinSchema, counts: Dict[int, int]):
    edges = np.asarray(schema.edges, dtype=float)
    k = schema.interior_bin_count
    interior = np.array([counts.get(i, 0) for i in range(1, k + 1)], dtype=float)
    return edges, interior


def wasserstein1_binned(
    schema_a: BinSchema,
    counts_a: Dict[int, int],
    schema_b: BinSchema,
    counts_b: Dict[int, int],
    *,
    grid_points: int = 1024,
) -> float:
    """Wasserstein-1 between two sparse bin-count maps under their schemas (ADR-005/016).

    Handles same-schema and cross-schema comparison uniformly via the shared grid. Overflow/underflow
    bins are excluded — they are the novelty signal (ADR-002), handled separately from drift distance.
    """
    ea, ca = _interior(schema_a, counts_a)
    eb, cb = _interior(schema_b, counts_b)
    return wasserstein1(ea, ca, eb, cb, grid_points=grid_points)
