# ADR-006 — Statistical Moments & Entropy from Binned Data

**Status:** Accepted
**Context layer:** Analytical core — the per-window statistical summary the project is named for (moments, percentiles, entropy, and the fingerprint vector, all derived from the histograms)
**Depends on:** ADR-002 (the bins, their edge positions and widths, the fixed value axis), ADR-003 (computed within one `bin_schema_id`), ADR-004 (computed over as-of-consistent snapshots).
**Related / logical-order note:** ADR-005 (drift) *consumes* the fingerprint this ADR produces. This ADR is logically upstream of ADR-005 despite its later number; the final numbering pass may reorder the two.
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

The system's defining premise — and its name — is that the **binned histogram is the
sufficient statistic** from which every per-window summary is derived: the central moments
(mean, variance, skewness, kurtosis), selected percentiles (p50, p90, p95, p99), and entropy.
These assemble into the per-`(instrument, channel, event_hour)` **fingerprint vector**
`[mean, variance, skewness, kurtosis, p50, p90, p95, p99, entropy]` that downstream layers
read.

Deriving everything from the one histogram is a deliberate architectural choice with a real
payoff: moments, percentiles, entropy, and drift are then all computed from the *same* as-of
snapshot, so they are **mutually consistent by construction** and inherit the histogram's
bitemporal, mergeable, as-of-queryable properties (ADR-002/003/004) for free. The cost is that
moments computed from grouped data carry a **quantization bias** — the histogram knows which
bin a reading fell in, not its exact value. The project accepts this in exchange for the
single-source-of-truth property, on the explicit condition that the bias is **bounded,
quantifiable, and corrected**.

That condition runs into a subtlety that must be faced directly. The classical tool for
grouped-moment bias — **Sheppard's corrections** — is derived for **equal-width** bins (a single
bin width *h*, with the variance correction −*h*²/12). But ADR-002 chose **variable-width,
equal-mass** bins. The textbook formula therefore does not apply as written, and pretending it
does would be wrong.

## Decision

**1. All moments, percentiles, and entropy are computed from the binned histogram (counts +
schema), not from a parallel exact-value accumulator.** The bin edge positions and widths come
from the schema (ADR-002); the proportions come from the counts. No raw-value power sums are
maintained alongside the bins. This keeps the increment fact (ADR-004) a pure count structure
and makes the histogram the single source of every statistic.

**2. Central moments use bin representative points with a grouped-data correction generalized
to variable widths.** Each bin contributes at its representative value (bin midpoint), weighted
by its proportion. The quantization bias is then removed not by a single −*h*²/12 term but by
the **mass-weighted per-bin quantization variance**: each bin of width *wᵢ* and proportion *pᵢ*
contributes a within-bin variance of *wᵢ²/12*, so the variance correction is **−Σ pᵢ·wᵢ²/12**,
with the analogous generalization for the higher moments. This is the correct generalization of
Sheppard's correction to unequal bins; classical Sheppard is its special case when all *wᵢ = h*.

**3. The equal-mass bin choice (ADR-002) is what makes this correction small — a synergy, not a
coincidence.** Equal-mass bins are *narrow where the data is dense* and wide only in the sparse
tails. Since the correction is mass-weighted (Σ *pᵢ·wᵢ²*), the wide bins carry little mass and
the bins carrying most of the mass are narrow — so the aggregate quantization bias is far
smaller than equal-width binning would produce at the same bin count. The decision made for
*percentile* accuracy pays a second dividend in *moment* accuracy.

**4. Percentiles are read from the cumulative histogram by interpolation within the containing
bin** (per ADR-002's no-separate-sketch decision): walk the cumulative proportions to the target
quantile and interpolate linearly across the bin it lands in. p50/p90/p95/p99 are produced this
way; their tail accuracy rests on the equal-mass bins keeping the tail bins populated. (Min/max
are reported at **bin resolution**, with the overflow/underflow bins of ADR-002 flagging
genuine beyond-historical extremes — exact extremes are not a histogram output.)

**5. Entropy is the discrete Shannon entropy of the bin proportions under the fixed schema,**
H = −Σ *pᵢ log pᵢ*. Its interpretation is deliberately *relative to the instrument's own
schema*: because equal-mass bins make the historical reference distribution uniform by
construction (ADR-002), the reference sits at **maximum** entropy, and a current distribution
that **concentrates** registers as an entropy *drop*. Entropy thus becomes a concentration
measure against the instrument's own normal — elegant for intra-instrument drift, and consistent
with the scoping in ADR-005. This is **binned** entropy (a property of the distribution under
this schema), explicitly not the differential entropy of the underlying physical signal.

**6. The fingerprint vector is assembled here and published per as-of snapshot,** for each
`(instrument, channel, event_hour)` at each materialized horizon (ADR-004). It is the
interpretable summary other layers consume.

## Alternatives considered

**Maintain exact running moments via power-sum / Welford accumulators (alongside the bins).**
This would make mean/variance/skewness/kurtosis *exact*, with no quantization bias, and power
sums are additive so they would fit the append-only bitemporal model. Seriously considered, and
rejected for two reasons. First, it introduces a **second structure that must be kept
bitemporally consistent** with the histogram across late data, corrections, and as-of queries —
two sources of truth that a bug could put into disagreement (a reported mean inconsistent with
the reported histogram). Second, it **contradicts the project's premise**: BinMoments asserts
that the binned histogram is a sufficient statistic from which moments derive at controlled,
quantifiable accuracy. Single source of truth plus a corrected, bounded approximation was chosen
over exactness-with-duplication. *(Retained as a designed-for refinement: if one specific channel
ever needs a moment more exact than bins-plus-correction delivers, per-channel exact accumulators
can be added, since they are additive and bitemporal-compatible — built only on a demonstrated
need.)*

**Apply classical Sheppard's correction unchanged.** Rejected: it assumes a single equal bin
width and would be simply incorrect over variable-width bins. The mass-weighted generalization is
required.

**Bin midpoint with no correction at all.** Simplest. Rejected: it leaves a known, quantifiable
bias in variance and kurtosis that the correction removes cheaply (the inputs — *pᵢ*, *wᵢ* — are
already on hand).

**Differential (continuous) entropy with the log-width term** (H_diff ≈ H_binned + Σ *pᵢ log wᵢ*).
This would make entropy comparable *across* schemas and instruments. Rejected for the core because
drift is intra-instrument under a fixed schema (ADR-005), where binned entropy is sufficient and
simpler. *(Designed-for: the log-width correction is added if cross-schema entropy comparability is
ever required.)*

## Consequences

**What this buys us.** One structure — the histogram — yields moments, percentiles, entropy, and
the fingerprint, all mutually consistent and all inheriting the bitemporal/as-of/mergeable
machinery already built. A grouped-moment bias that is bounded, corrected, and — because of the
equal-mass bins — small. An entropy measure that doubles as a concentration signal against the
instrument's own normal.

**A count-unbiased aggregation property (a genuine selling point).** Because each
`(instrument, channel, event_hour)` yields exactly **one** statistical summary regardless of how
many raw measurements arrived that hour, aggregating across days, weeks, or a month is **unbiased
by per-period measurement count**. A naive system that averages raw readings over a month implicitly
weights each day by how many readings it happened to record, so days that sampled more often dominate
the monthly figure; BinMoments does not, because the per-hour aggregation already normalized sampling
density out. The hourly summary is the unit of aggregation, not the raw reading. This is a real
statistical-correctness advantage of the per-hour-one-statistic structure (ADR-002/ADR-004), and it is
worth stating explicitly in the companion document.

**Moments come from the native variable bins, never from a resampled grid.** The cross-schema
comparison grid introduced for drift (ADR-016) is a fixed-*width* resampling used **only** to make two
histograms from different schema versions commensurable for a distance computation. Moments, percentiles,
and entropy are always computed from the **native variable bins** with the ADR-006 correction — computing
them from the equal-width comparison grid would reintroduce exactly the equal-width quantization that
variable bins were chosen to avoid, on top of resampling loss. The comparison grid is strictly
drift-comparison-only and must not leak into the measurement path.

**What it costs.** Moments are approximate, not exact. The approximation is the price of
single-source-of-truth, and the project owns it explicitly: it is corrected (mass-weighted
grouped-data correction), bounded, and **quantified in the companion document** — the
bin-size/precision analysis the project promised, which derives how fine the bins must be for a
target accuracy on each moment. That document is the rigorous backing for the name BinMoments,
and it is where the full correction formulae and the quantization-error derivation live; this ADR
states the decision, the appendix proves it.

**A caveat to record.** Grouped-data corrections of Sheppard type assume the underlying density is
reasonably smooth and tapers at the tails. For a channel with a hard physical cutoff or a sharply
truncated distribution the higher-order corrections can be unreliable; such channels are flagged
to fall back to midpoint-without-higher-correction, and the precision document notes the
condition.

**Scope discipline (over-engineering guards).**
- Moments come from the bins, with the mass-weighted correction — no parallel exact-accumulator
  structure is built unless a specific channel demonstrably needs it.
- Entropy is the simple binned Shannon entropy; the differential-entropy log-width correction is
  designed-for, not built.
- Circular channels (ADR-001) require circular moments (circular mean/variance) and a circular
  entropy treatment; deferred with the rest of the circular-statistics work until the wind-bearing
  channel exists.

**Coupling to other decisions.** Consumes ADR-002's bins (edges, widths, fixed axis), stays within
one `bin_schema_id` per ADR-003, and is computed over ADR-004's as-of snapshots so every fingerprint
is reproducible. The fingerprint it produces is consumed by ADR-005 — where, importantly, it is
*not* compared by cosine (that was rejected there); the histograms are compared directly for drift,
and the fingerprint serves as the interpretable summary and the basis for the designed-for
Mahalanobis second opinion.

---

*Authorship: architecture and all design decisions by the author. Implementation is AI-assisted —
code generated against the documented architecture and decisions. This ADR records the reasoning;
the code is the proof.*
