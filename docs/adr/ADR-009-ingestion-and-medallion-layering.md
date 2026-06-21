# ADR-009 — Ingestion & Medallion Layering

**Status:** Accepted
**Context layer:** Pipeline structure (how raw JSON becomes the bitemporal increment fact and analytical products)
**Depends on:** ADR-001 (channel decomposition), ADR-003 (re-binning on schema refit), ADR-004 (signed deltas, arrival_time, correction identity), ADR-006 (materializations), ADR-007 (registry join), ADR-008 (contract).
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

The analytical spine (ADR-002 through ADR-006) assumes measurements arrive already binned into the
increment fact, but never specifies *how* raw JSON gets there. That path must preserve enough to
satisfy three earlier commitments that turn out to depend on it: re-binning historical data under a
new `bin_schema_id` when a schema is refit (ADR-003) **requires the raw values to still exist**;
tracing a correction to the measurement it restates (ADR-004) requires a durable measurement
identity; and recovering from a binning bug requires that binning not be the only record. All three
demand a raw layer beneath the fact.

## Decision

**1. Adopt a medallion-style layering, mapped to this domain** (the same shape proven in LogLens):

- **Bronze — raw landing.** Append-only, verbatim JSON plus ingestion metadata; `arrival_time` is
  stamped here; **hash-based idempotency** makes re-ingestion safe (as in LogLens). The durable
  `measurement_id` lives here — this is where correction traceability is anchored, resolving the
  ADR-004 note that the count fact deliberately holds no per-measurement identity.
- **Silver — parsed, validated, normalized.** Measurements are decomposed into channels (ADR-001),
  time-normalized to UTC, validated against the contract (ADR-008), and registry-joined (ADR-007).
  Late data and corrections are resolved here into the **signed deltas** of ADR-004.
- **Gold — analytical products.** The bitemporal binned increment fact (ADR-004), the fixed-horizon
  moment/entropy materializations (ADR-006), and the drift signals (ADR-005).

**2. ELT, not ETL, at the boundary** (as in LogLens): bronze lands raw with minimal transformation so
ingestion rarely fails; shaping happens downstream where it can be retried safely.

**3. Each layer is independently re-runnable and reads only its own upstream** (layer isolation, as in
LogLens), so binning can be re-run from bronze without re-ingesting, and a schema refit re-bins from
bronze under a new `bin_schema_id`.

## Alternatives considered

**Ingest JSON straight into the increment fact (no raw layer).** Simplest and least storage. Rejected
decisively: it loses the raw values, which makes re-binning on schema refit (ADR-003) **impossible**,
severs correction-to-source traceability (ADR-004), and leaves no recovery path from a binning bug.
Bronze raw landing is a hard dependency of the schema-lifecycle decision, not an optional nicety.

**A bespoke two-layer (raw → fact) pipeline.** Considered, but the silver layer earns its place:
channel decomposition, validation, registry join, and correction resolution are real transformation
steps that belong between raw and the analytical fact. Collapsing them into either neighbour muddies
responsibilities.

## Consequences

**What this buys us.** Raw fidelity that makes schema-refit re-binning and correction traceability
possible (closing the open dependencies from ADR-003 and ADR-004), recoverability, and a structure
already proven in LogLens — a consistency a reviewer will recognize across the two projects.

**What it costs.** Storage at each layer; a multi-step pipeline. Accepted for recoverability and
auditability, the same trade LogLens made.

**Scope discipline.** Three layers, no more; no speculative extra staging. Streaming vs. batch is not a
layering question — Structured Streaming (ADR-010) serves both over the same layers.

**Coupling.** This ADR is the connective tissue: it ties ADR-008's contract to ADR-001's channels, to
ADR-004's deltas and identity, to ADR-003's re-binning, to ADR-006's materializations, joined against
ADR-007's registry.

---

*Authorship: architecture and all design decisions by the author. Implementation is AI-assisted.
This ADR records the reasoning; the code is the proof.*
