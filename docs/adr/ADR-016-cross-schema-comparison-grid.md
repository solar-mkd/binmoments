# ADR-016 — Cross-Schema Comparison Grid (CDF Resampling)

**Status:** Accepted
**Context layer:** Analytical core — the mechanism that makes histograms from different schema versions comparable for drift, without violating the merge prohibition
**Depends on:** ADR-002 (variable bins, fixed value axis), ADR-003 (schema versioning and the merge prohibition), ADR-005 (which needs year-over-year comparison), ADR-006 (which must *not* use this grid for moments).
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

Two earlier decisions are in tension, and reading the set as a whole surfaced it. ADR-002/003 make
bin edges **data-derived and frozen per schema version**, and forbid merging counts across versions
because two schemas place mass on different edges. ADR-003 also **refits the schema annually**, minting
a new version. But ADR-005 wants to compare an instrument against its own **prior year** and against a
**historical reference** — comparisons that, by construction, cross a schema-refit boundary and so land
on two *different* edge sets. Native bin-to-bin comparison is impossible across that boundary: the bins
do not line up.

The resolution rests on a distinction that dissolves the tension. ADR-003's prohibition is on
**merging** — *summing* counts — because summation across mismatched edges is meaningless. But drift does
not need to merge two histograms; it needs only to make their **distributions commensurable** enough to
measure a distance between them. Commensurability does not require shared bins — only a shared evaluation
domain. That is achievable on the fly, without storing anything and without ever summing across versions.

## Decision

**1. To compare two histograms from different schema versions, resample both onto a common fixed grid
and compute the distance there.** The grid is a fixed number of points (default **1024**) spanning the
union of the two histograms' value ranges. Nothing about the grid is persisted; it is computed
per-comparison and discarded.

**2. Resample the cumulative distribution (CDF), not the density.** This is the decision that makes the
procedure exact and assumption-free. The CDF is **known precisely at every bin edge** — it is the running
sum of bin proportions — and it is **monotonic**. Resampling it onto the grid is therefore plain monotone
interpolation between known points: no density-smoothing, no approximation function to discover, no risk of
ringing or negative values. (Interpolating the *density* would require guessing a smooth shape and is
exactly the fragile step to avoid.)

**3. Compute 1-D Wasserstein as the integral of the absolute CDF difference on the grid.** Because
1-D Wasserstein distance *is* the integral of |CDF₁ − CDF₂|, and both CDFs are now sampled on the same
grid, the distance is a simple sum over the grid — fast and numerically trivial.

**4. The grid is for cross-version comparison only; same-version comparisons skip it.** When both
histograms share a `bin_schema_id`, drift is computed directly on the native variable bins (ADR-005), which
is cheaper and avoids any resampling loss. The grid is invoked only at a refit boundary.

**5. The grid never feeds the measurement path.** Moments, percentiles, and entropy are always computed
from the native variable bins (ADR-006). The grid is equal-*width* by construction, so using it for moments
would reintroduce the equal-width quantization that variable bins were chosen to avoid — explicitly
prohibited.

## Alternatives considered

**Resample the density and interpolate a smooth approximating function** (the first instinct, including an
FFT-based smoothing at 1024 points). Rejected: it requires choosing an approximation family, can introduce
ringing and negative densities, and adds machinery (FFT) for no benefit — because the distance needed
(1-D Wasserstein) is a CDF integral, and the CDF needs no smoothing. The FFT motivation disappears once the
problem is framed on the CDF.

**Forbid cross-version comparison entirely** (treat every refit as a hard reset of drift history). Rejected:
it would discard year-over-year drift detection, one of the system's most valuable signals, and would make
the `historical_reference` baseline unusable across a refit.

**Re-bin all history under the newest schema whenever a refit occurs.** Possible (the raw layer, ADR-009,
retains the values to do it), but expensive and unnecessary for *comparison*: it rewrites stored history to
solve a problem that an on-the-fly, nothing-stored resampling solves. Re-binning remains the right tool for
*other* purposes (e.g. migrating an instrument's analysis fully to a new schema), not for routine drift
comparison.

## Consequences

**What this buys us.** Year-over-year and historical-reference drift comparison across schema refits, with
ADR-003's merge prohibition fully intact — merging is still forbidden, only *comparison* is enabled. The
procedure is exact up to interpolation (monotone CDF, known points), stores nothing, and is cheap.

**What it costs.** A resampling step at refit boundaries (negligible — 1024-point monotone interpolation),
and a small amount of interpolation error, bounded and far smaller than the quantization the variable bins
already control.

**Scope discipline.** Fixed grid, CDF-only, comparison-only, nothing persisted, no FFT. The grid is a
narrow bridge between schema versions, not a general resampling layer; it is confined to the drift
comparison and explicitly barred from the measurement path.

**Coupling.** Invoked by ADR-005 at refit boundaries; respects ADR-003 (no merging); kept out of ADR-006
(no moments from the grid); relies on ADR-009's raw layer only indirectly (the histograms it compares are
already materialized).

---

*Authorship: architecture and all design decisions by the author. Implementation is AI-assisted.
This ADR records the reasoning; the code is the proof.*
