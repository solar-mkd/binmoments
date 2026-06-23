"""Intra-instrument drift detection — the headline anomaly signal.

See ADR-005. Wasserstein distance over the binned distributions (cosine rejected), compared
against a per-instrument baseline, with self-calibrated thresholds. Cross-schema comparison
(year-over-year) uses the shared grid of ADR-016.
"""

from .detector import DriftDetector, calibrate_threshold, pool_counts
from .distance import wasserstein1, wasserstein1_binned

__all__ = [
    "wasserstein1",
    "wasserstein1_binned",
    "DriftDetector",
    "calibrate_threshold",
    "pool_counts",
]
