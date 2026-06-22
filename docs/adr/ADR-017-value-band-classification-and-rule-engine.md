# ADR-017 — Value-Band Classification & (Designed-For) Rule Engine

**Status:** Accepted (bands); Designed-for (rule engine)
**Context layer:** Alerting / classification — a familiar operational banding alongside the distribution-distance drift signal
**Depends on:** ADR-005 (drift, the primary signal this complements), ADR-011 (per-instrument configuration), ADR-001 (channels).
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

Operators expect a familiar, legible status for a measurement: is it **Nominal, Elevated, Warning, or Critical**? This banding is commodity functionality, but it is genuinely useful — it is the status a dashboard shows at a glance — and it complements, rather than competes with, the distribution-distance drift signal (ADR-005). Drift answers "is this instrument's *distribution* changing?"; banding answers "is the *current value* in a concerning range?" They are different questions and both have their place.

There is also a richer idea on the table, drawn from a prior production system: a configurable **decision-table rule engine** in which the value range is divided into arbitrarily many bands by a table of rows `(from, to, if-yes-goto, if-no-goto)`, where a negative target halts and returns a verdict — a compact, flexible, almost Turing-machine-like encoding that lets users define arbitrary banded classifications, and could be extended to compose conditions over `{value, drift, mean, deviation, …}`. The question is how much of this belongs in BinMoments.

## Decision

**1. Static value-band classification is built into the core.** Each instrument's configuration (ADR-011) defines band thresholds; each reading — and each `(instrument, channel, event_hour)` — is classified Nominal / Elevated / Warning / Critical. Because the system already maintains the hourly histogram, the banding composes naturally with it: the system can report **what fraction of an hour's mass fell in each band**, not merely the band of a single latest reading. This is a few lines of logic over existing structures, and it earns its place.

**2. The general, user-composed rule engine is fenced as designed-for — not built in the slice.** A configurable engine that lets users compose multi-condition rules over a vector of derived quantities (value, drift, mean, deviation, percentile, …) with decision-table flow control is recorded, with its decision-table design (the `(from, to, if-yes-goto, if-no-goto)`, negative-target-halts encoding) sketched for the future, and explicitly deferred.

## Alternatives considered

**Build the full rule engine into the core now.** Rejected as scope expansion of the over-engineering kind: a configurable multi-condition rule engine is effectively a second system — an expression language with evaluation semantics, validation, a configuration grammar, a UI or DSL, and its own test surface — with little connection to the distribution-fingerprinting thesis that makes BinMoments distinctive. It would also risk **inverting the project's story**: BinMoments' headline is that Wasserstein drift against a self-calibrated baseline (ADR-005) detects distributional change a static threshold cannot. Placing a hand-built rule engine beside it invites the reading "a thresholding system with some statistics bolted on" — the opposite of the intended signal. The statistics are the headline; banding is commodity.

**Build nothing (drift only).** Rejected: the four-band status is cheap, expected by operators, and complements drift. Omitting it would be austere for no benefit.

## Consequences

**What this buys us.** A legible operational status next to the sophisticated drift signal, computed cheaply over the existing histogram — including the richer "fraction of mass per band" view that a raw-reading thresholder cannot produce.

**What it costs.** A small amount of per-instrument band configuration (ADR-011).

**Scope discipline (over-engineering fence).** Static bands **in**; the general user-composed rule engine **fenced**. The decision-table design is recorded so that, if built, it is built deliberately — trigger: after the core drift detection is validated against ground truth (ADR-008). The line is drawn precisely: classification of a value into configured bands is core; arbitrary user-defined rule composition is a future, separable feature.

**Coupling.** Reads per-instrument band thresholds from configuration (ADR-011); sits alongside the drift signal of ADR-005; classifies the channels of ADR-001 over the histograms of ADR-002.

---

*Authorship: architecture and all design decisions by the author. Implementation is AI-assisted. This ADR records the reasoning; the code is the proof.*
