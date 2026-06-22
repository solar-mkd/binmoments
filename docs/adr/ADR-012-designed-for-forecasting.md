# ADR-012 — Designed-For: Forecasting on the Fingerprint

**Status:** Designed-for (not built)
**Context layer:** Future extension (predictive analytics on top of the validated core)
**Depends on:** ADR-005 (drift signals), ADR-006 (fingerprint time series), ADR-008 (ground truth for evaluation).
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

Original requirement point 7 envisions ML to forecast future values and anticipate instrument failure. This is a large, separable problem and a classic place for a portfolio project to balloon past completion. It is therefore **recorded as a designed-for extension and explicitly not built in the vertical slice**, with the design pinned so it extends the core rather than bolting a generic model onto the side.

## Decision (deferred)

When built, forecasting **operates on the fingerprint / moment time series (ADR-006), not on raw values**: it forecasts the fingerprint (or a key moment) forward and flags when reality deviates from the forecast. This keeps it tied to the system's existing unit of analysis and its drift machinery, rather than introducing a parallel generic time-series stack.

**Trigger to build:** after the core drift detector is validated against ground truth (ADR-008), so forecasting extends a *validated* baseline and can itself be scored against injected faults.

## Alternatives noted

A generic raw-value forecaster is rejected as unfocused — predict the fingerprint, which is what drives drift, not the raw signal. Building before the core is validated is rejected — there would be no ground truth to evaluate the forecaster against.

## Consequences

Deferred; the fingerprint and drift signals (ADR-005/006) are the designed interface it will consume. Fence: not built until the trigger condition is met.

---

*Authorship: architecture by the author; implementation AI-assisted. This ADR records a deferred decision.*
