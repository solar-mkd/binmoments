"""Self-calibrated, intra-instrument drift detection (ADR-005).

Drift is measured *within* an instrument, against its own normal — never by a global threshold and
never across instruments (that is the fenced spatial capability, ADR-018). The detector:

1. takes a **reference** distribution that represents the instrument's normal (a baseline window);
2. measures the Wasserstein distance of each new window to that reference;
3. flags a window when the distance exceeds a **self-calibrated threshold** learned from the
   instrument's own normal window-to-window variation — so each instrument sets its own bar.

The baseline policy (what counts as "normal") is configurable (ADR-005): a fixed clean reference
period, a trailing window, or a same-period-last-year distribution to absorb seasonality. This module
provides the mechanism; the caller chooses the reference.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

import numpy as np

from ..binning.schema import BinSchema
from .distance import wasserstein1_binned


def pool_counts(counts_list: Iterable[Dict[int, int]]) -> Dict[int, int]:
    """Pool several same-schema bin-count maps into one reference distribution (sum counts)."""
    pooled: Dict[int, int] = {}
    for counts in counts_list:
        for b, c in counts.items():
            pooled[b] = pooled.get(b, 0) + c
    return pooled


def calibrate_threshold(distances: Iterable[float], *, k: float = 8.0) -> float:
    """A robust self-calibrated threshold from normal window distances: median + k * (scaled MAD).

    The median and MAD (median absolute deviation) describe the instrument's *normal* window-to-window
    variation; a window must exceed that normal scatter by ``k`` robust deviations to be called drift.
    Using the median/MAD rather than the mean/std keeps the bar from being inflated by the very
    excursions it is meant to catch.
    """
    d = np.asarray(list(distances), dtype=float)
    d = d[~np.isnan(d)]
    if d.size == 0:
        raise ValueError("no calibration distances provided")
    med = float(np.median(d))
    mad = float(np.median(np.abs(d - med)))
    scaled = 1.4826 * mad  # MAD -> standard-deviation-equivalent for a normal
    if scaled == 0.0:
        # Degenerate (all distances identical): fall back to a margin over the observed maximum.
        return float(max(d) * 1.5) if max(d) > 0 else 0.0
    return med + k * scaled


@dataclass(frozen=True)
class DriftDetector:
    """A calibrated detector for one instrument/channel: reference distribution + threshold."""

    schema: BinSchema
    reference_counts: Dict[int, int]
    threshold: float

    @classmethod
    def calibrate(
        cls,
        schema: BinSchema,
        reference_windows: List[Dict[int, int]],
        *,
        k: float = 8.0,
    ) -> "DriftDetector":
        """Build a detector from a set of clean reference windows.

        The reference distribution is the pool of the clean windows; the threshold is calibrated from
        each clean window's distance to that pooled reference (the instrument's normal scatter).
        """
        reference = pool_counts(reference_windows)
        distances = [
            wasserstein1_binned(schema, w, schema, reference) for w in reference_windows
        ]
        threshold = calibrate_threshold(distances, k=k)
        return cls(schema=schema, reference_counts=reference, threshold=threshold)

    def distance(self, counts: Dict[int, int]) -> float:
        """Wasserstein distance of a window to the reference, in value units."""
        return wasserstein1_binned(self.schema, counts, self.schema, self.reference_counts)

    def is_drift(self, counts: Dict[int, int]) -> bool:
        """True if the window's distance to the reference exceeds the self-calibrated threshold."""
        return self.distance(counts) > self.threshold

    def score_series(
        self,
        windows: Iterable[Tuple[object, Dict[int, int]]],
    ) -> List[Tuple[object, float, bool]]:
        """Score an ordered series of (key, counts) windows -> [(key, distance, is_drift), ...]."""
        out: List[Tuple[object, float, bool]] = []
        for key, counts in windows:
            d = self.distance(counts)
            out.append((key, d, d > self.threshold))
        return out
