"""Exact statistical moments from additive power sums (ADR-006).

A handful of running sums — the count and the sums of the first four powers of the values — are a
*sufficient statistic* for the mean, variance, skewness, and kurtosis. Computed this way the moments
are **exact**: there is no binning bias, unlike reading moments off bin midpoints (which ADR-006's
revision note documents as biased 5–90% for equal-mass bins).

The sums are **additive**, so they ride the bitemporal fact's machinery for free (ADR-004 decision
2a): combining two windows is adding their PowerSums; an as-of query sums the contributions whose
arrival is at or before the cutoff; a correction subtracts the old reading's powers and adds the new.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class PowerSums:
    """Additive sums (n, Sigma x, Sigma x^2, Sigma x^3, Sigma x^4) — a sufficient statistic for moments."""

    n: float = 0.0
    s1: float = 0.0
    s2: float = 0.0
    s3: float = 0.0
    s4: float = 0.0

    @classmethod
    def from_values(cls, values: Iterable[float]) -> "PowerSums":
        x = np.asarray(list(values), dtype=float)
        if x.size == 0:
            return cls()
        return cls(
            n=float(x.size),
            s1=float(x.sum()),
            s2=float((x ** 2).sum()),
            s3=float((x ** 3).sum()),
            s4=float((x ** 4).sum()),
        )

    def __add__(self, other: "PowerSums") -> "PowerSums":
        return PowerSums(
            self.n + other.n,
            self.s1 + other.s1,
            self.s2 + other.s2,
            self.s3 + other.s3,
            self.s4 + other.s4,
        )

    # --- moments (exact) --------------------------------------------------------------------

    @property
    def mean(self) -> float:
        return self.s1 / self.n

    def _central(self) -> tuple:
        """Return (m2, m3, m4): the 2nd/3rd/4th central moments, by raw-to-central conversion."""
        mu = self.s1 / self.n
        a2, a3, a4 = self.s2 / self.n, self.s3 / self.n, self.s4 / self.n
        m2 = a2 - mu ** 2
        m3 = a3 - 3 * mu * a2 + 2 * mu ** 3
        m4 = a4 - 4 * mu * a3 + 6 * mu ** 2 * a2 - 3 * mu ** 4
        return max(m2, 0.0), m3, m4  # clamp m2 against tiny negative float error

    @property
    def variance(self) -> float:
        return self._central()[0]

    @property
    def std(self) -> float:
        return math.sqrt(self.variance)

    @property
    def skewness(self) -> float:
        m2, m3, _ = self._central()
        return m3 / m2 ** 1.5 if m2 > 0 else 0.0

    @property
    def kurtosis_excess(self) -> float:
        """Excess kurtosis (0 for a normal distribution)."""
        m2, _, m4 = self._central()
        return m4 / m2 ** 2 - 3.0 if m2 > 0 else 0.0
