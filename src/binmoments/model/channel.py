"""Channel definition and value decomposition (ADR-001).

A measurement of any tensor rank is reduced to one or more scalar *channels*: the statistical
engine downstream is univariate and only ever sees scalar magnitudes.

- rank 0 (scalar, e.g. temperature): magnitude is the value; no direction.
- rank 1 (vector, e.g. wind):         magnitude is the vector length; direction is a unit vector.
- rank 2 (tensor, e.g. conductivity): DESIGNED-FOR, not built — see ADR-015. The decomposition is
  the eigendecomposition (a named invariant as magnitude, the eigenbasis as direction); we raise
  here rather than guess an implementation against synthetic data, keeping the fence explicit.

Each channel also carries a ``linear | circular`` kind flag (ADR-001). Circular quantities (e.g. a
wind bearing) need circular statistics and wrap-around bins downstream; the flag is carried here,
and the circular *statistical* treatment is deferred until the first circular channel is built.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence


class ChannelKind(str, Enum):
    """Whether a scalar channel lives on a line or on a circle (ADR-001)."""

    LINEAR = "linear"
    CIRCULAR = "circular"


# Ranks the model represents; rank >= 3 is an explicit non-goal (ADR-001).
_SUPPORTED_RANKS = (0, 1, 2)
# Ranks actually implemented today; rank 2 is designed-for (ADR-015) and raises on decomposition.
_BUILT_RANKS = (0, 1)


@dataclass(frozen=True)
class Channel:
    """A named scalar/vector/tensor channel of a measurement (ADR-001)."""

    name: str
    rank: int
    kind: ChannelKind
    unit: str

    def __post_init__(self) -> None:
        if self.rank not in _SUPPORTED_RANKS:
            raise ValueError(
                f"channel '{self.name}': rank {self.rank} is out of scope; BinMoments models "
                f"ranks {_SUPPORTED_RANKS} (rank >= 3 is a non-goal, ADR-001)."
            )
        if not isinstance(self.kind, ChannelKind):
            raise ValueError(
                f"channel '{self.name}': kind must be a ChannelKind, got {self.kind!r}."
            )


@dataclass(frozen=True)
class Decomposition:
    """Reduction of a raw value to the statistical engine's scalar input (ADR-001).

    ``magnitude`` is the scalar fed to bins/moments. ``direction`` is retained provenance:
    None for rank-0, a unit vector for rank-1, an eigenbasis for rank-2 (when built).
    """

    magnitude: float
    direction: Optional[Sequence[float]] = None


def decompose(channel: Channel, value) -> Decomposition:
    """Decompose a raw measurement value into magnitude (+ direction) per ADR-001.

    The magnitude is what the bin/moment engine consumes; the direction is kept as provenance
    and is only promoted to its own channel where directional drift is in scope (ADR-001).
    """
    if channel.rank == 0:
        return Decomposition(magnitude=float(value), direction=None)

    if channel.rank == 1:
        vec = [float(v) for v in value]
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            # Direction is undefined for a zero vector; magnitude is 0.
            return Decomposition(magnitude=0.0, direction=None)
        unit = [v / norm for v in vec]
        return Decomposition(magnitude=norm, direction=unit)

    # rank == 2: deliberately not built (ADR-015).
    raise NotImplementedError(
        f"channel '{channel.name}': rank-2 tensor decomposition is designed-for, not built "
        f"(eigendecomposition: invariant as magnitude, eigenbasis as direction). See ADR-015."
    )
