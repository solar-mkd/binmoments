"""Baseline temperature field: seasonal + diurnal cycle plus noise (ADR-008).

The deterministic part (seasonal + daily cycles) is separated from the stochastic noise so that
fault injection can scale the noise (variance inflation) or offset the mean independently — and so
that two runs sharing a seed differ ONLY by the injected faults. That separation is what makes the
ground truth exact, which is the whole point of the simulator.

Defaults model a Brisbane-like climate: southern hemisphere, warmest in late January.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TemperatureField:
    """A smooth seasonal + diurnal mean temperature, in degrees Celsius."""

    annual_mean: float = 21.0          # mean temperature over the year
    seasonal_amplitude: float = 6.0    # peak-to-mean swing across the year
    daily_amplitude: float = 5.0       # peak-to-mean swing across the day
    noise_std: float = 1.5             # std of the per-reading noise
    peak_day_of_year: float = 20.0     # ~late January (southern-hemisphere summer)
    peak_hour: float = 14.0            # warmest in mid-afternoon

    def deterministic(self, when: datetime) -> float:
        """Seasonal + diurnal mean temperature at ``when``, without noise."""
        seconds_into_day = when.hour * 3600 + when.minute * 60 + when.second
        day_of_year = when.timetuple().tm_yday + seconds_into_day / 86400.0
        hour = when.hour + when.minute / 60.0 + when.second / 3600.0

        seasonal = self.annual_mean + self.seasonal_amplitude * math.cos(
            2 * math.pi * (day_of_year - self.peak_day_of_year) / 365.25
        )
        daily = self.daily_amplitude * math.cos(
            2 * math.pi * (hour - self.peak_hour) / 24.0
        )
        return seasonal + daily
