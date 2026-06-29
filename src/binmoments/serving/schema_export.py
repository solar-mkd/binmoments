"""Export a bin schema's edges as plain rows, for persisting and plotting.

A histogram is only plottable with its bin EDGES (the x-axis), not bin indices,
and with empty bins shown as zero. The analytical schema carries the edges; this
turns them into a flat table the serving layer and a plotting view can join the
bin counts against.
"""

from __future__ import annotations

from math import isinf
from typing import List, Tuple

# (bin_index, lower_edge, upper_edge, midpoint)
EdgeRow = Tuple[int, float, float, float]


def schema_edge_rows(schema, *, edges_attr: str = "edges") -> List[EdgeRow]:
    """Return [(bin_index, lower_edge, upper_edge, midpoint), ...] for a schema.

    Expects the schema to expose its bin edges as an ascending sequence of length
    n_bins + 1 under ``edges_attr`` (bin b spans [edges[b], edges[b+1])). If your
    BinSchema names this differently (e.g. ``bin_edges``), pass ``edges_attr=`` or
    adjust here. Open outer bins (a -inf or +inf edge) take their finite neighbour
    as the representative midpoint so they remain plottable.
    """
    edges = getattr(schema, edges_attr, None)
    if edges is None:
        raise AttributeError(
            f"BinSchema has no attribute {edges_attr!r}; pass edges_attr= to match your API"
        )
    edges = [float(e) for e in edges]
    if len(edges) < 2:
        raise ValueError("a schema must have at least two edges (one bin)")

    rows: List[EdgeRow] = []
    for b in range(len(edges) - 1):
        lo, hi = edges[b], edges[b + 1]
        if isinf(lo) and isinf(hi):
            mid = 0.0
        elif isinf(lo):
            mid = hi
        elif isinf(hi):
            mid = lo
        else:
            mid = 0.5 * (lo + hi)
        rows.append((b, lo, hi, mid))
    return rows
