"""The frozen, versioned bin-schema artifact (ADR-003).

A BinSchema is a derived-and-frozen description of how one channel's values are sliced into bins.
It is identified by a content-derived ``schema_id``: the same fitting data and parameters always
produce the same id, and any change to the edges (e.g. an annual refit on new data) produces a new
id automatically. Counts are tagged with this id and must never be merged across ids (ADR-003); the
merge guard itself lives in the aggregation layer (ADR-004), but the identity it keys on is here.

Bin index convention (ADR-002): index 0 is the UNDERFLOW bin (values below the historical minimum),
indices 1..K are the K interior variable-width bins, and index K+1 is the OVERFLOW bin (values above
the historical maximum). Overflow/underflow are the novelty signal — a value beyond a year of
observation lands there.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

import numpy as np


def compute_schema_id(
    scope: str,
    channel: str,
    edges: Tuple[float, ...],
    fit_start: str,
    fit_end: str,
) -> str:
    """Deterministic content id. Excludes creation time so the same data yields the same id."""
    rounded = ",".join(f"{e:.6f}" for e in edges)
    payload = f"{scope}|{channel}|{fit_start}|{fit_end}|{rounded}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"bm_{digest}"


@dataclass(frozen=True)
class BinSchema:
    """A frozen, versioned binning artifact for one channel (ADR-002 method, ADR-003 lifecycle)."""

    schema_id: str
    scope: str                  # e.g. "instrument:TEMP-001" or "type:ambient_temperature"
    channel: str
    edges: Tuple[float, ...]    # K+1 interior edges; edges[0]=historical min, edges[-1]=historical max
    fit_start: str              # provenance: start of the fitting window (ISO-8601)
    fit_end: str                # provenance: end of the fitting window (ISO-8601)
    created_at: Optional[str] = None  # provenance only; NOT part of the id

    @property
    def interior_bin_count(self) -> int:
        return len(self.edges) - 1

    @property
    def total_bin_count(self) -> int:
        return self.interior_bin_count + 2  # + underflow + overflow

    @property
    def value_min(self) -> float:
        return self.edges[0]

    @property
    def value_max(self) -> float:
        return self.edges[-1]

    def assign(self, value: float) -> int:
        """Return the bin index for one value (0=underflow, 1..K interior, K+1=overflow)."""
        v = float(value)
        if v < self.edges[0]:
            return 0
        if v > self.edges[-1]:
            return self.interior_bin_count + 1
        e = np.asarray(self.edges, dtype=float)
        idx = int(np.searchsorted(e, v, side="right"))
        # v == max collapses to the last interior bin rather than overflow.
        return min(max(idx, 1), self.interior_bin_count)

    def bin_counts(self, values: Iterable[float]) -> Dict[int, int]:
        """Vectorized sparse histogram: {bin_index: count} for non-empty bins only (ADR-002)."""
        v = np.asarray(list(values), dtype=float)
        v = v[~np.isnan(v)]
        if v.size == 0:
            return {}
        e = np.asarray(self.edges, dtype=float)
        k = self.interior_bin_count
        under = v < e[0]
        over = v > e[-1]
        interior = np.clip(np.searchsorted(e, v, side="right"), 1, k)  # 1..K (v==max -> K)
        bin_ids = np.where(under, 0, np.where(over, k + 1, interior))
        ids, counts = np.unique(bin_ids, return_counts=True)
        return {int(i): int(c) for i, c in zip(ids, counts)}

    def normalize(self, value: float) -> float:
        """The frozen value-axis transform (ADR-002): map [min, max] -> [0, 1], linearly.

        Identical across all windows by construction (it depends only on the frozen edges), which is
        what ADR-002 requires; values outside the historical range map below 0 or above 1.
        """
        lo, hi = self.edges[0], self.edges[-1]
        return (float(value) - lo) / (hi - lo)

    def compatible_with(self, other: "BinSchema") -> bool:
        """Two schemas may have their counts merged only if they share an id (ADR-003)."""
        return self.schema_id == other.schema_id
