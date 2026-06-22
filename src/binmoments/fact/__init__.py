"""Bitemporal increment fact and as-of reproducibility.

See ADR-004. Append-only signed-delta fact with valid time (event_hour) and transaction
time (arrival_time); as-of reconstruction, fixed-horizon materializations, and corrections
via compensating deltas.
"""

from .increment import EntryType, IncrementRow
from .store import IncrementFact, floor_to_hour, measurement_increment

__all__ = [
    "IncrementFact",
    "IncrementRow",
    "EntryType",
    "floor_to_hour",
    "measurement_increment",
]
