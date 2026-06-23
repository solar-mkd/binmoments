"""Static value-band classification.

See ADR-017. Fixed Nominal/Elevated/Warning/Critical bands that compose with the histogram
(band occupancy read from bin counts). A general user-composed rule engine is fenced for later.
"""

from .scheme import BandScheme

__all__ = ["BandScheme"]
