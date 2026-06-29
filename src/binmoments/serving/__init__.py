"""Serving layer: materialized read models derived from the increment fact.

These are derived, rebuildable projections of the append-only fact (ADR-004):
caches for fast reads, never a source of truth. Any object here can be discarded
and reconstructed exactly by replaying the fact. See ADR-020.
"""

from .current_state import CurrentStateHistogram, increments_to_items
from .schema_export import schema_edge_rows

__all__ = ["CurrentStateHistogram", "increments_to_items", "schema_edge_rows"]
