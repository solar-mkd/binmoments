# ADR-019 — Designed-For: Zero-Inflated & Heavy-Tailed Channels

**Status:** Designed-for (not built)
**Context layer:** Future extension (channels whose distribution breaks the equal-mass binning and Sheppard assumptions)
**Depends on:** ADR-002 (equal-mass binning), ADR-006 (moments, and its smoothness caveat), ADR-001 (channels).
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

Temperature — the channel the vertical slice is built on — is a well-behaved continuous quantity: a single smooth mode, tails that taper. The core's two key statistical choices assume exactly this. Equal-mass binning (ADR-002) assumes the value can be sliced into bins of roughly equal probability mass; the generalized Sheppard correction (ADR-006) assumes a density that is smooth and tapers at the tails.

**Rainfall breaks both assumptions, and does so in a way that is central to the Australian context.** In many regions rain is rare — most hours and many days record **exactly zero** — and when it occurs it **spikes** heavily. This is a *zero-inflated, heavy-tailed* distribution: a large point mass at zero plus a long, sparse positive tail. Two failures result:

- **Equal-mass binning fails at the zero spike.** If (say) 90% of values are exactly zero, there is no way to divide that mass into equal-mass bins — it is a single atom, not a continuum. Forcing equal-mass bins either creates absurd zero-width bins at zero or lumps the meaningful positive values into one coarse bin.
- **Sheppard's correction is unreliable.** ADR-006 already flagged that grouped-data corrections assume a smooth density tapering at the tails; a spike at zero with a heavy positive tail violates this directly.

So zero-inflated channels cannot simply be fed through the temperature path. They need a distinct model — which is *why rainfall is a valuable future channel*: it proves the architecture handles hard distributions, not just the easy one.

## Decision (deferred)

When a zero-inflated channel (rainfall, and similar) is onboarded, model it as a **hybrid: a discrete component plus a continuous component.**
- Separate the **dry mass** (exact zeros, or values below a configured wet/dry threshold) as its own discrete component, tracked as a **dry-fraction statistic** per instrument-hour. The dry fraction is itself a meaningful signal (drought onset, a blocked gauge) and a clean input to drift detection.
- Bin **only the positive "wet" values** with the equal-mass scheme of ADR-002, which behaves correctly once the zero atom is removed and only the continuous wet tail remains.
- Compute moments/entropy over the wet component (where Sheppard's smoothness assumption is restored), reported alongside the dry fraction rather than blended into a single misleading summary.

Drift detection (ADR-005) then operates on **both** components — a change in dry fraction *or* a change in the wet distribution is drift — which is richer than a single-distribution view.

**Trigger to build:** when rainfall (or any zero-inflated channel) is onboarded as a real channel — deliberately after the temperature slice is complete, because this is the *hard* distribution to graduate to, not the one to start with.

## Alternatives noted

Forcing zero-inflated data through the standard equal-mass path is rejected — it produces meaningless bins at the zero atom and unreliable moments. Treating the zero atom as just another small bin is rejected — it hides the dry-fraction signal that is operationally important (and physically central in arid regions). Building this now is rejected — the slice is temperature; rainfall is the graduation case.

## Consequences

Deferred; recorded so the limitation of the core (smooth-distribution assumption) is named honestly and the hybrid model is ready when rainfall arrives. Makes rainfall a strong future channel precisely because it stress-tests and extends the architecture. Fence: not built until a zero-inflated channel is onboarded.

---

*Authorship: architecture by the author; implementation AI-assisted. This ADR records a deferred decision.*
