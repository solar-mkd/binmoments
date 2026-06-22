"""Bin schema derivation and provenance/lifecycle.

See ADR-002 (variable-width equal-mass bins; edges from value distribution, count from
measurement density; overflow anchored to historical extreme) and ADR-003 (frozen,
versioned bin_schema_id; per-type default + per-instrument override; annual refit).
"""

from .derive import derive_bin_schema, recommend_bin_count
from .schema import BinSchema, compute_schema_id

__all__ = ["BinSchema", "compute_schema_id", "derive_bin_schema", "recommend_bin_count"]
