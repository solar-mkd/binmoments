# ADR-008 — Sensor Data Contract & Synthetic Simulator

**Status:** Accepted
**Context layer:** Ingestion boundary (the shape of incoming measurements, and the synthetic generator that produces them with known ground truth)
**Depends on:** ADR-001 (channels), ADR-004 (event/arrival time, late data, corrections), ADR-007 (instrument identity).
**Referenced by:** ingestion (ADR-009); validation of ADR-005 (drift) and ADR-006 (moments).
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

There is no real sensor fleet, so the system needs both a **defined contract** for incoming
measurements (original requirement point 2) and a **simulator** to produce them. The simulator
has two distinct jobs, and the second is the important one: produce realistically-shaped IoT
data, and — critically — inject **known** drift, anomalies, late data, and corrections so the
analytical core can be **validated against ground truth**. LogLens earned its credibility from
one line: it was validated end-to-end. BinMoments' equivalent is a detector that demonstrably
catches faults whose timing and nature are known because the simulator put them there.

## Decision

**1. The measurement contract is versioned JSON accepting either a single measurement or an
array of measurements** (batch), reflecting real store-and-forward devices. Each measurement
carries: `instrument_id` (ADR-007), an event timestamp with explicit timezone/UTC, the per-channel
value(s) (scalar, or vector decomposed per ADR-001), and an optional `measurement_id` used as the
anchor for corrections (ADR-004). Ingestion stamps `arrival_time`.

**2. The simulator generates realistic baseline distributions per channel** — e.g. ambient
temperature with daily and seasonal cycles — at **configurable, modest per-instrument sampling
rates**, consistent with ADR-002's finding that per-instrument-per-hour counts are small.

**3. The simulator injects labelled ground-truth faults on a schedule:** distribution drift (mean
shift, variance inflation, skew), anomalies (spikes, beyond-range values that exercise the overflow
bins of ADR-002), sensor faults (stuck value; direction-freeze for vector channels), **late
arrivals**, and **corrections**. Every injected event is logged as ground truth so detection can be
scored (precision/recall on the drift detector of ADR-005).

**4. Late data and corrections are first-class in the simulator** — it can emit a measurement for a
past `event_hour` with a later `arrival_time`, and emit a correction referencing a prior
`measurement_id` — so ADR-004's bitemporal machinery is exercised in practice, not merely asserted.

**5. All generated data is synthetic and safe to commit** (as in LogLens), and the system is
reproducible from a clean clone.

## Alternatives considered

**Use a public IoT dataset as the primary source.** Rejected as primary: with real data you do not
*know* exactly when or what drift occurred, so you cannot score the detector. Ground-truth-labelled
synthetic data is required for validation. Real data is a designed-for add-on for realism, layered
on after the detector is validated.

**Single-measurement-only contract.** Rejected: batch arrays are common in real IoT and supporting
both from the start is cheap.

**Happy-path-only generation.** Rejected: the system exists to detect faults, so the simulator must
produce faults — with known timing — or there is nothing to validate against.

## Consequences

**What this buys us.** End-to-end validation of the analytical core against ground truth; genuine
exercise of the bitemporal/correction machinery; reproducibility. This is the decision that lets the
project claim "validated," not "implemented."

**What it costs.** Simulator realism is an ongoing investment.

**Scope discipline (over-engineering guard).** The slice simulates **one scalar channel** (temperature)
with injected drift, anomalies, late data, and corrections. Multi-channel, vector (wind), and
high-fidelity physical models are designed-for. The goal is statistically realistic,
ground-truth-labelled streams — **not** a physics engine.

**Coupling.** Feeds ingestion (ADR-009); produces the ground truth against which ADR-005 and ADR-006
are scored; exercises ADR-004.

---

*Authorship: architecture and all design decisions by the author. Implementation is AI-assisted.
This ADR records the reasoning; the code is the proof.*
