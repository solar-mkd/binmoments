"""Synthetic sensor-data generator with ground-truth fault injection.

See ADR-008 (sensor data contract & synthetic simulator). The simulator emits realistic
streams AND injects known drift/anomalies so the analytical core can be validated against
ground truth.
"""

from .faults import DriftWindow, FaultKind, GroundTruthEvent, Spike, StuckWindow
from .simulator import Simulator
from .temperature_field import TemperatureField

__all__ = [
    "Simulator",
    "TemperatureField",
    "DriftWindow",
    "StuckWindow",
    "Spike",
    "FaultKind",
    "GroundTruthEvent",
]
