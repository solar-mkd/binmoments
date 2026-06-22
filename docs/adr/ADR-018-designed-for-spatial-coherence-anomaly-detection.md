# ADR-018 — Designed-For: Spatial Coherence Anomaly Detection

**Status:** Designed-for (not built)
**Context layer:** Future extension (a cross-instrument anomaly signal complementary to temporal drift)
**Depends on:** ADR-005 (temporal drift, which this complements), ADR-007 (geodetic location), ADR-008 (the simulator must generate spatially-correlated data before this can be validated).
**Relates to:** ADR-014 (general cross-instrument similarity — this is a narrower, physically-grounded case).
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

Temporal drift (ADR-005) compares an instrument to its own past, which gives it a specific blind spot: a sensor that is **consistently wrong** — miscalibrated by a fixed offset since installation — exhibits no drift, because nothing is changing. It is steadily, quietly incorrect, and ADR-005 cannot see it. A second, independent signal is needed to catch this class of fault.

Geography provides it. Instruments that are physically close generally measure a similar underlying field, so an instrument that **diverges from its geographic neighbors** is a candidate for being faulty — even when it is internally stable. This is **spatial outlier detection**, and it is genuinely complementary to temporal drift: drift catches *change over time*; spatial coherence catches *disagreement with the neighborhood now*.

This capability is **cross-instrument**, which ADR-005 deliberately scoped out (drift is intra-instrument) and ADR-014 set aside (general fleet similarity). Spatial coherence is the legitimate, narrower return of cross-instrument comparison: it is constrained by physical proximity rather than by abstract distribution similarity, which makes it both more tractable and more defensible than general fleet clustering.

## The honest difficulty (recorded now, not glossed)

"Close instruments read alike" is **not universally true**, and the exception is exactly the phenomenon that motivates much of this project's Australian context: **localized rainfall**. Convective rain is spatially patchy — one gauge records a downpour while another a few kilometres away stays dry, and that disagreement is *real weather, not a fault*. Naive spatial correlation would raise false alarms precisely on spiky, localized events.

Two consequences follow, and both belong in the eventual design:

- **Spatial coherence is channel-dependent.** It is strong for smooth fields (temperature varies gently over space) and weak and treacherous for localized phenomena (convective rainfall). The method must know each channel's **spatial correlation length** and weight neighbor comparisons accordingly — trusting neighbors strongly for temperature, weakly (or not at all) for convective rain.
- **The method must distinguish "diverges because broken" from "diverges because the phenomenon is genuinely local."** That separation — not the neighbor comparison itself — is the hard part, and the reason this is a real capability rather than a one-line "nearby things are similar" rule.

## Decision (deferred)

When built, the capability:
- uses the geodetic positions of ADR-007 to define each instrument's spatial neighborhood;
- compares an instrument's distribution (or fingerprint, ADR-006) against an aggregate of its neighbors, raising a signal on divergence — using the **same distribution-distance machinery** as ADR-005 (Wasserstein), now applied across space rather than across time;
- **weights neighbor agreement by the channel's spatial correlation length**, so localized channels do not generate false alarms;
- treats the result as a complement to, not a replacement for, temporal drift — the two together catch both the *changing* sensor and the *consistently-wrong* sensor.

**Trigger to build:** after the temporal core (ADR-005) is validated against ground truth, and only once the simulator (ADR-008) can generate **spatially-correlated multi-sensor data** with known, injected faults — without that ground truth, spatial detection cannot be scored. The simulator's geographic correlation and this capability are built together, as one unit.

## Alternatives noted

Naive "flag any divergence from neighbors" is rejected — it false-alarms on genuinely local phenomena (convective rain). Folding this into ADR-005's intra-instrument drift is rejected — it is a distinct cross-instrument signal with its own failure modes. Building the simulator's spatial correlation now, ahead of this capability, is rejected as premature (the slice is single-sensor; multi-sensor spatial generation is built when this is).

## Consequences

Deferred; recorded so the idea is captured and its genuine difficulty (channel-dependence, local phenomena) is named rather than discovered late. Reuses the geodetic metadata (ADR-007) and the distance machinery (ADR-005), so building it is extension, not new infrastructure. Fence: not built until the trigger is met.

---

*Authorship: architecture by the author; implementation AI-assisted. This ADR records a deferred decision.*
