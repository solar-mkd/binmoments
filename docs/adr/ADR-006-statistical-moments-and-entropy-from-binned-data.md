# ADR-006 — Statistical Moments & Entropy

**Status:** Accepted — **revised during implementation** (see Revision note). Originally titled "…from Binned Data"; the binned-moment method was reversed after numerical validation.
**Context layer:** Analytical core — the per-window statistical summary the project is named for (moments, percentiles, entropy, and the fingerprint vector)
**Depends on:** ADR-002 (the bins, used for percentiles and entropy), ADR-004 (the bitemporal fact, which now also carries power-sum deltas for exact moments), ADR-003 (computed within one `bin_schema_id`).
**Related / logical-order note:** ADR-005 (drift) *consumes* the fingerprint this ADR produces. This ADR is logically upstream of ADR-005 despite its later number; the final numbering pass may reorder the two.
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Revision note (what changed and why)

This ADR originally decided that *all* statistics — including the central moments — would be computed from the binned histogram, using bin midpoints with a generalized (variable-width) Sheppard correction. **Numerical validation during the moments build refuted that decision.** Computing variance from equal-mass bins via midpoints overestimated the true variance by **5% to 90%** depending on bin count (and skewness/kurtosis worse), because equal-mass binning makes the *tail* bins very wide, and a wide bin's midpoint is a poor stand-in for mass that is actually bunched near the bin's inner edge. The Sheppard correction did not rescue it: that correction assumes a uniform spread within each bin, and that assumption is most violated exactly in the wide tail bins that dominate the error.

The decision was therefore reversed: **moments are computed exactly from running power-sum accumulators, not from the bins.** The bins are retained for the statistics they genuinely excel at — percentiles and entropy — where the distribution shape, not a representative value, is what is needed. This change also *restores the author's original instinct*: the first description of the system noted "I don't need the histograms to calculate min, max, average and std. deviation" — the over-consolidation onto bins was introduced by the original draft of this ADR, and validation undid it. (Evidence summary retained below under Alternatives.)

## Context

The system summarizes each scalar channel per instrument-hour into a **fingerprint**: `[mean, variance, skewness, kurtosis, p50, p90, p95, p99, entropy]`, which downstream layers read. These are three different *kinds* of statistic, and they are not all best served by the same structure:

- **Moments** (mean, variance, skewness, kurtosis) summarize *level and shape* and are defined as sums of powers of the values. They want the actual values, not a bucketed approximation.
- **Percentiles** (p50/p90/p95/p99) are *positional* — they ask "what value sits at this rank" — and are read naturally off the cumulative distribution the bins already represent.
- **Entropy** is a *distribution-shape* statistic over the bin proportions, and carries a clean interpretation under the equal-mass schema (the historical reference is uniform, i.e. maximum entropy, so concentration shows up as an entropy drop).

The binned histogram is the right tool for the latter two and the wrong tool for the first (see the Revision note and Alternatives). So the moments and the shape-statistics are sourced differently — on purpose.

## Decision

**1. Moments are computed exactly from running power-sum accumulators.** Per `(instrument, channel, event_hour)` the system maintains `n` and `Σx, Σx², Σx³, Σx⁴`. From these the mean, variance, skewness, and (excess) kurtosis follow by closed form, with **no binning bias** — they use the real values, not bin representatives.

**2. The power sums are stored as additive signed deltas in the bitemporal fact (ADR-004).** Each measurement contributes `(Δn, Δx, Δx², Δx³, Δx⁴)` at its `event_hour`/`arrival_time`; a correction subtracts the wrong value's powers and adds the right one's. As-of and horizon queries sum the power deltas with `arrival_time ≤` the cutoff — so **moments are reproducible as-of any past instant**, inheriting exactly the same bitemporal machinery as the bin counts. The moments are exact at every as-of point, not merely at "final".

**3. Percentiles are read from the variable-mass bins (ADR-002),** by walking the cumulative counts to the target rank and interpolating within the containing bin. Equal-mass bins keep the tail bins populated, so p95/p99 are well resolved — this is the job the bins are *good* at.

**4. Entropy is the discrete Shannon entropy of the bin proportions (ADR-002),** `H = −Σ pᵢ ln pᵢ`, reported in nats and also normalized to `[0,1]` by `ln K`. Because equal-mass bins make the historical reference uniform by construction, the reference sits at maximum entropy and a *concentrating* distribution registers as an entropy drop — a concentration signal against the instrument's own normal. This is binned entropy under the schema, explicitly not the differential entropy of the underlying signal.

**5. The fingerprint is assembled here** from the exact moments (1), the bin percentiles (3), and the bin entropy (4), per as-of snapshot.

## Alternatives considered

**Moments from bins via midpoint + generalized Sheppard correction (the original decision).** Rejected on numerical evidence. For normal data with true variance 9.0, the midpoint method gave:

```
 bins | midpoint variance | error      | centroid variance | error
------+-------------------+------------+-------------------+--------
   16 |      17.17        |  +91%      |       8.80        |  -2%
   64 |      11.00        |  +22%      |       8.96        |  -0.4%
  256 |       9.46        |  +5%       |       8.99        |  -0.1%
```

The midpoint overestimate is large and only slowly improves with bin count; the Sheppard correction (either sign) barely moves it, because its uniform-within-bin premise fails precisely in the wide tail bins. Higher moments (skew, kurtosis) weight the tails by the cube and fourth power and are worse. Equal-mass binning is excellent for percentiles and entropy and unsuitable for midpoint moments — so moments were moved off the bins entirely.

**Per-bin centroids (store each bin's value-sum and use the mass mean instead of the midpoint).** Much better — sub-1% variance error even at modest bin counts (the "centroid" column above). Rejected in favor of full power sums because centroids still ignore within-bin spread (variance stays slightly biased) and require per-bin storage, whereas a handful of power sums per window are *exact* and simpler.

**Single source of truth = the histogram (the original rationale for binned moments).** Rejected: the histogram is **not** a sufficient statistic for the moments under equal-mass binning, so the single-source aesthetic was bought at the price of wrong numbers. Correctness wins. Power sums are additive and bitemporal-compatible, so they cost very little of the consistency the single-source argument was protecting.

**Maintain power sums but compute moments only at "final" (ignore as-of for moments).** Rejected: the power sums are additive deltas, so as-of and horizon reconstruction is free — there is no reason to give up reproducible moments.

## Consequences

**What this buys us.** Exact, unbiased moments (mean, variance, skewness, kurtosis) at any as-of instant and any horizon, from five small accumulators per window. Well-resolved tail percentiles and a meaningful concentration-entropy, from the bins. Each structure now does what it is good at, with no redundancy: bins for shape (percentiles, entropy, drift), power sums for moments.

**The count-unbiased aggregation property still holds — and is now exact.** Because each `(instrument, channel, event_hour)` yields one summary regardless of how many readings arrived, aggregating across days or a month is unbiased by per-period measurement count (a naive average of raw readings over-weights densely-sampled periods). With power sums this aggregation is also numerically exact. This is a genuine statistical-correctness advantage worth stating in the companion document.

**Moments never come from any bin representative or resampled grid.** Not from bin midpoints (refuted above), and not from the cross-schema comparison grid (ADR-016), which is equal-width and drift-only. Moments come solely from the exact power sums.

**What it costs.** Five additive accumulators per window in the fact (tiny), and the conceptual point that the fingerprint is sourced from two structures rather than one. The "BinMoments" name still holds: the system maintains binned distributions *and* statistical moments per window — moments computed alongside the bins, not derived from them.

**Scope discipline (over-engineering guards).**
- Power sums up to the 4th are maintained (mean…kurtosis); no higher moments unless a need appears.
- Circular channels (ADR-001) need circular moments (circular mean/variance) and a circular entropy treatment; deferred with the rest of the circular-statistics work until the wind-bearing channel.
- The companion document derives the closed-form moments from power sums and quantifies the (now small) residual considerations; the bin-size/precision analysis now concerns percentile and entropy resolution, not moment accuracy (moments are exact).

**Coupling.** Power sums are stored and reconstructed by ADR-004; percentiles and entropy read ADR-002 bins within one `bin_schema_id` (ADR-003); the fingerprint is consumed by ADR-005 — where it is *not* compared by cosine (rejected there), and serves as the interpretable summary and the basis for the designed-for Mahalanobis second opinion.

---

*Authorship: architecture and all design decisions by the author. Implementation is AI-assisted — code generated against the documented architecture and decisions. This ADR records the reasoning, including a decision reversed by evidence during the build; the code is the proof.*
