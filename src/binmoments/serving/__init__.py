"""Serving layer: materialized read models derived from the increment fact.

These are derived, rebuildable projections of the append-only fact (ADR-004).
They are caches for fast reads, never a source of truth: any current-state
object here can be discarded and reconstructed exactly by replaying the fact.
See ADR-020.
"""

from .current_state import CurrentStateHistogram, increments_to_items

__all__ = ["CurrentStateHistogram", "increments_to_items"]
