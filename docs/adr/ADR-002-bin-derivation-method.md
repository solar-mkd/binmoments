# ADR-002 — Bin Derivation Method

**Status:** Accepted
**Context layer:** Statistical core — histogram definition (how a channel's bins are shaped; read by every moment, percentile, and drift computation)
**Depends on:** ADR-001 (Measurement & Channel Model) — bins are defined *per channel*; each channel carries a `linear | circular` flag this ADR must respect.
**Related:** ADR-003 (Bin Schema Provenance & Lifecycle) — governs how the schema this ADR derives is frozen, versioned, and refit.
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

The system summarizes each scalar channel (per ADR-001) as a streaming histogram: incoming measurements increment bin counts, and those counts are the raw material for moments, entropy, percentiles, and distribution-distance drift detection. How the bins are *shaped* therefore determines the accuracy of everything downstream. This is the most consequential statistical decision in the project.

The naive choice — fixed-width bins over the channel's range — fails in a specific, disqualifying way. Bin *width* is uniform, but the quantity we care about is probability *mass*. Real sensor data (ambient temperature, for example) is concentrated: most readings sit in a narrow band, with sparse tails. Fixed-width bins put dense, well-resolved bins in the populated middle and starved, low-resolution bins in the tails — which is backwards, because the tail percentiles (p95, p99) live in those starved bins, and the tails are where anomalies appear. Fixed-width bins give good middle percentiles and poor tail percentiles, the opposite of what an anomaly-detection system needs.

Two further forces shape the method. First, the histogram is a **statistical estimator**, subject to bias and variance: more bins is not simply "more accurate." More bins means fewer counts per bin, which means each bin's proportion is noisier. Resolution is only useful where there are enough measurements to fill it. Second, a practical fact discovered during design reframes the bin-count question: "millions of measurements" is a *system-wide* figure, not a per-instrument-per-hour one. A single instrument may produce only tens of readings in an hour. The binding constraint on bin count is therefore the **measurement count in the smallest comparison window**, not the breadth of the value range.

## Decision

**1. Bins are variable-width, derived from the empirical quantiles of at least one year of historical data, so that each bin holds approximately equal probability mass.** Edges are placed denser where the data is dense and coarser in the sparse tails — fine resolution where readings actually occur, including good tail resolution for percentiles. A minimum of one year of history is required so the edges bracket the full seasonal range rather than being blown out by the first out-of-season reading.

**2. Two distinct statistics drive two distinct outputs of the derivation, and they must not be conflated:**
   - **Edge placement** (including the overflow boundary and the value-axis transform) is derived from the **value distribution** — where the data lives, how heavy the tails are.
   - **Bin count** is derived from the **measurement density per comparison window** — how many readings a typical window contains — *not* from the value range. Two instruments with identical ranges but different sampling rates get different bin counts.

**3. Bin count is bounded by statistics, not by compute.** Incrementing is O(1) per measurement regardless of bin count; counts are stored **sparse** (only non-empty bins), so storage is bounded by readings-per-window, not schema size; distance and moment computations are O(bins) and negligible even at 1000 bins. The real limit is estimator variance: a schema must not have so many bins that a typical comparison window leaves most of them empty. Thin per-hour windows are therefore compared only in their aggregated horizons (24h, 7d), where counts are dense enough for fine bins to carry signal.

**4. The overflow / underflow boundary is anchored to the observed historical extreme, not to a fixed percentile.** The outermost regular bins are placed at (or just beyond) the minimum and maximum actually observed in the training year; explicit overflow and underflow bins capture anything beyond. A reading landing in overflow then means "a value beyond anything this instrument produced in a year" — a genuine novelty signal. (A fixed percentile such as p99 is rejected: it would route ~1% of *normal* readings into overflow every hour, making overflow the resting state rather than a signal. p99.9 is retained only as a sanity check that the boundary has not been drawn too tight.)

**5. The value-axis transform (value → normalized axis) is fixed and identical across every window; per-window rescaling is prohibited.** Normalizing each window to its own min/max would map an hour at 20–25 °C and an hour at 30–35 °C onto the same normalized range, algebraically *deleting* the very shift the system exists to detect. The transform is derived once, from the training year, and applied unchanged across all windows. (This is distinct from, and in addition to, **mass normalization** — scaling counts so each histogram sums to 1 — which is required for the distance metrics and is applied at comparison time, not at binning time. The transform and edges, taken together, are the artifact that ADR-003 freezes and versions.)

**6. Percentiles are read directly from the variable-bin histogram (cumulative counts); no separate percentile sketch is maintained.** Because equal-mass bins already give good tail resolution, walking the cumulative counts to the desired quantile is accurate enough, and avoids carrying a second mechanism.

## Alternatives considered

**Fixed-width bins over the channel range.** Simplest to implement and trivially mergeable. Rejected: uniform width gives starved, low-resolution tail bins exactly where the operationally important percentiles (p95/p99) and anomalies live. Good middle, poor tails — the wrong trade for this system.

**Hand-tuned multi-tier widths** (e.g. 0.1 °C in 20–30, 0.5 °C in 15–20, coarser outside). Captures the right intuition but by manual specification per instrument — unscalable, subjective, and a maintenance burden. Rejected in favor of choosing a single target bin count and letting the empirical quantiles place the edges automatically; the algorithm concentrates resolution where the data is, with no hand tuning. *(Over-engineering guard: the method is data-driven, not a hand-built tier table.)*

**A separate percentile sketch (DDSketch / t-digest) layered on top of the histogram.** Considered, and initially attractive when bins were assumed fixed-width — tail percentiles were starved, so a sketch with guaranteed relative error earned its place. Rejected *because of decision (1)*: equal-mass variable bins already give good tail resolution, so percentiles can be read directly from the histogram. Adding a sketch would be two mechanisms for one job. Recorded as a designed-for extension, to be revisited only if hard guaranteed-relative-error percentiles are later required.

**Per-window value-axis normalization.** Rejected — see decision (5); it deletes the drift signal by construction.

## Consequences

**What this buys us.** Accurate moments, entropy, and — critically — tail percentiles, because resolution follows the data. A clean, principled novelty signal (overflow = beyond a year of observation). A drift comparison that is honest, because the value axis is fixed across windows.

**An elegant by-product.** Because equal-mass bins make the training-year distribution *uniform by construction* in bin space, "has this instrument drifted from its historical self" reduces to "how far has its current histogram moved from flat" — a cheap, clean reference for the drift metric (a later ADR).

**Cross-instrument comparison is given up by this choice — deliberately.** Two instruments with different edge sets are not directly comparable bin-to-bin. This is acceptable *only because* drift was scoped as intra-instrument (each instrument against its own past). The two decisions are linked: variable bins are safe precisely because cross-instrument bin comparison was already out of scope.

**Cross-*version* comparison (same instrument, across a schema refit) is handled by resampling, not merging.** The same data-derived edges that forbid *summing* counts across schema versions (ADR-003) would also block *comparing* an instrument to its own prior year, which the drift layer needs. The resolution is that comparison does not require commensurable *bins* — only commensurable *distributions*: both histograms are resampled onto a common fixed grid (ADR-016) and the distance is computed there. Merging is still forbidden; comparison is enabled. This keeps ADR-003's safety intact while satisfying ADR-005's year-over-year need.

**Scope discipline (over-engineering guards).**
- Edges are placed algorithmically from quantiles, never hand-tuned per instrument.
- No separate percentile sketch is built; percentiles come from the variable bins. DDSketch is designed-for, built only if guaranteed-error percentiles are needed.
- Bin count is chosen against the smallest comparison window's count, not pushed high because compute allows it; fine resolution is spent only where the counts justify it.
- Circular channels (per ADR-001) require wrap-around bin topology; the method accommodates it, but the circular binning implementation is deferred with the circular-statistics implementation until the first circular channel (wind bearing).

**Coupling to later decisions.** The frozen artifact this ADR produces (edges + value-axis transform) is versioned and governed by ADR-003. The drift metric (Wasserstein over channel histograms) reads these bins and depends on mass normalization at comparison time and on the fixed value axis defined here. The moments/entropy computation reads the same bins (with Sheppard's correction for the binning bias, handled in its own ADR).

---

*Authorship: architecture and all design decisions by the author. Implementation is AI-assisted — code generated against the documented architecture and decisions. This ADR records the reasoning; the code is the proof.*
