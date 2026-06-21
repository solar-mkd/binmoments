# ADR-013 — Designed-For: Cross-Measurement Correlation Mining

**Status:** Designed-for (not built)
**Context layer:** Future extension (relationships across different measurements and instruments)
**Depends on:** ADR-006 (fingerprint/moment series), ADR-005 (drift signals).
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

Original requirement point 8 envisions discovering relationships across measurements — e.g. rain now
predicting wind a week later. This is genuinely useful and genuinely a footgun: naive correlation mining
over seasonal environmental data produces mostly **spurious** correlations (everything correlates through
the shared seasonal cycle), and large pairwise searches inflate false positives without multiple-testing
control. It is recorded as designed-for, with the guards that make it credible captured now so it is built
rigorously or not at all.

## Decision (deferred)

When built, correlation mining **operates on the fingerprint / moment time series across instruments and
channels**, with three guards mandatory:
- **Seasonality controlled** before correlating (deseasonalize, or correlate residuals / same-phase
  windows), so shared cycles do not manufacture correlation.
- **Multiple-testing correction** and spurious-correlation guards across the pairwise search.
- **Explicit lag/lead structure**, since the value (rain → wind *a week later*) is in the lag.

Results are framed as **hypotheses to investigate, never causal claims**.

**Trigger to build:** after the core and forecasting are in place and validated.

## Alternatives noted

Naive pairwise correlation is rejected (spurious via seasonality and multiple testing). Causal
interpretation is rejected — this surfaces candidate relationships, not causation.

## Consequences

Deferred; the guards are documented so that, if built, it is defensible. The honest acknowledgment of the
footguns is itself the reason to record it now. Fence: not built until the trigger is met.

---

*Authorship: architecture by the author; implementation AI-assisted. This ADR records a deferred decision.*
