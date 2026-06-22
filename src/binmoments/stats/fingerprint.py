"""The per-window fingerprint: exact moments + bin percentiles + bin entropy (ADR-006).

The fingerprint is sourced from two structures on purpose (ADR-006 revision): the **moments** come
from exact power sums (no binning bias), the **percentiles and entropy** come from the bins (where
the distribution shape lives). ADR-005 consumes this fingerprint — comparing distributions directly
for drift, and using the fingerprint as the interpretable summary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from ..binning.schema import BinSchema
from .power_sums import PowerSums
from .shape import entropy_from_bins, percentiles_from_bins


@dataclass(frozen=True)
class Fingerprint:
    """A per-(instrument, channel, event_hour) statistical summary."""

    # exact moments (from power sums)
    n: float
    mean: float
    variance: float
    std: float
    skewness: float
    kurtosis_excess: float
    # positional + shape (from bins)
    p50: float
    p90: float
    p95: float
    p99: float
    entropy_nats: float
    entropy_normalized: float
    # provenance
    channel: Optional[str] = None
    bin_schema_id: Optional[str] = None

    def vector(self) -> List[float]:
        """The fingerprint vector in canonical order (ADR-006).

        [mean, variance, skewness, kurtosis_excess, p50, p90, p95, p99, entropy_normalized]
        """
        return [
            self.mean,
            self.variance,
            self.skewness,
            self.kurtosis_excess,
            self.p50,
            self.p90,
            self.p95,
            self.p99,
            self.entropy_normalized,
        ]


def assemble_fingerprint(
    power_sums: PowerSums,
    bin_counts: Dict[int, int],
    schema: BinSchema,
) -> Fingerprint:
    """Build a Fingerprint from a window's exact power sums and its bin counts."""
    pct = percentiles_from_bins(schema, bin_counts, [0.5, 0.9, 0.95, 0.99])
    h_nats, h_norm = entropy_from_bins(bin_counts, schema.interior_bin_count)
    return Fingerprint(
        n=power_sums.n,
        mean=power_sums.mean,
        variance=power_sums.variance,
        std=power_sums.std,
        skewness=power_sums.skewness,
        kurtosis_excess=power_sums.kurtosis_excess,
        p50=pct[0.5],
        p90=pct[0.9],
        p95=pct[0.95],
        p99=pct[0.99],
        entropy_nats=h_nats,
        entropy_normalized=h_norm,
        channel=schema.channel,
        bin_schema_id=schema.schema_id,
    )
