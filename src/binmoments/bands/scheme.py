"""Static value-band classification (ADR-017).

Bands answer a different question than drift (ADR-005). Drift asks whether an instrument has changed
*relative to its own normal*; bands ask whether the values sit in a meaningful *absolute* range —
Nominal, Elevated, Warning, Critical — regardless of whether anything changed. A perfectly stable
sensor can still be reading in a Critical range, and bands catch that.

The scheme is intentionally static (fixed value thresholds), and it **composes with the histogram**:
band occupancy — the fraction of a window's mass in each band — is read straight off the stored bin
counts, no rescan of raw values needed. A general, user-composed rule engine (combining bands with
drift, persistence, rate-of-change, etc.) is deliberately fenced for later (ADR-017); this is the
static foundation it would build on.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np

from ..binning.schema import BinSchema


@dataclass(frozen=True)
class BandScheme:
    """Ordered value bands defined by ascending boundaries (N boundaries -> N+1 labelled bands).

    Band index increases with value, so severity comparisons are simple ("at least Warning" is
    ``band_index(v) >= labels.index('Warning')``). Occupancy assumes monotonic severity: overflow
    mass (above the historical max) folds into the top band, underflow into the bottom band.
    """

    channel: str
    boundaries: Tuple[float, ...]   # ascending; the cut points between bands
    labels: Tuple[str, ...]         # one more than boundaries

    def __post_init__(self):
        if len(self.labels) != len(self.boundaries) + 1:
            raise ValueError("labels must have exactly one more entry than boundaries")
        if list(self.boundaries) != sorted(self.boundaries):
            raise ValueError("boundaries must be ascending")

    @classmethod
    def severity(cls, channel: str, *, elevated: float, warning: float, critical: float) -> "BandScheme":
        """The standard four-band severity scheme for an upper-hazard channel."""
        return cls(
            channel=channel,
            boundaries=(elevated, warning, critical),
            labels=("Nominal", "Elevated", "Warning", "Critical"),
        )

    def band_index(self, value: float) -> int:
        """The band index for a value (0 = lowest band)."""
        return int(np.searchsorted(np.asarray(self.boundaries, dtype=float), float(value), side="right"))

    def classify(self, value: float) -> str:
        """The band label for a single value (exact)."""
        return self.labels[self.band_index(value)]

    def occupancy(self, schema: BinSchema, counts: Dict[int, int]) -> Dict[str, float]:
        """Fraction of a window's mass in each band, read from the histogram (ADR-017).

        Interior bins are split across the bands they overlap (proportional to width, assuming
        uniform spread within a bin); overflow mass folds into the top band and underflow into the
        bottom band. The returned fractions sum to 1 (over all mass), so a hour can be summarized as,
        e.g., 96% Nominal / 4% Warning.
        """
        edges = np.asarray(schema.edges, dtype=float)
        k = schema.interior_bin_count
        interior = np.array([counts.get(i, 0) for i in range(1, k + 1)], dtype=float)
        under = float(counts.get(0, 0))
        over = float(counts.get(k + 1, 0))
        total = interior.sum() + under + over

        occ = {label: 0.0 for label in self.labels}
        if total <= 0:
            return occ

        band_lo = np.array([-np.inf, *self.boundaries], dtype=float)
        band_hi = np.array([*self.boundaries, np.inf], dtype=float)

        for i in range(k):
            if interior[i] == 0:
                continue
            lo, hi = edges[i], edges[i + 1]
            width = hi - lo
            mass = interior[i] / total
            if width <= 0:
                occ[self.labels[self.band_index(lo)]] += mass
                continue
            for j, label in enumerate(self.labels):
                overlap = max(0.0, min(hi, band_hi[j]) - max(lo, band_lo[j]))
                if overlap > 0:
                    occ[label] += mass * (overlap / width)

        occ[self.labels[-1]] += over / total     # beyond historical max -> top band
        occ[self.labels[0]] += under / total     # below historical min -> bottom band
        return occ
