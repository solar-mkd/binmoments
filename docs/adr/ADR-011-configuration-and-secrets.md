# ADR-011 — Configuration & Secrets

**Status:** Accepted
**Context layer:** Cross-cutting (how per-instrument behaviour is declared and how secrets are handled)
**Depends on:** ADR-001 (channels, linear/circular), ADR-003 (per-type/per-instrument inheritance), ADR-005 (drift rules), ADR-007 (registry linkage).
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

Several decisions have pushed behaviour into configuration rather than code: channel definitions and their `linear | circular` flags (ADR-001), bin-schema bindings (ADR-002/003), the per-instrument drift rule lists (ADR-005), and registry/label linkage (ADR-007). Configuration is therefore load-bearing and deserves its own decision record — including how secrets are kept out of it. This mirrors the philosophy that made LogLens governable: behaviour is configuration, secrets are never committed, and missing secrets fail closed.

## Decision

**1. Per-instrument behaviour is declarative configuration, not code:** channel definitions and flags, bin-schema binding, drift rule list, labels, and registry/location linkage. Onboarding an instrument is a configuration change, never a code change.

**2. Type-level defaults with per-instrument overrides** — the same inheritance model ADR-003 chose for bin schemas, applied uniformly to all configuration. New instruments inherit their type's defaults; mature or special instruments override.

**3. Configuration is versioned.** Changes to drift rules or channel definitions are tracked, so a report can know which configuration was in effect at a given time — consistent with the bitemporal thinking of ADR-004 and ADR-007.

**4. Secrets are never in configuration or committed.** Connection strings, cloud credentials, and any HMAC salts/keys (if a PII-style policy is applied to instrument metadata) are supplied via the platform secret store (Databricks secrets / Unity Catalog) and **referenced, not embedded**. If a required secret is absent, the pipeline **fails closed** rather than running in an unsafe state — the same discipline as LogLens's PII handling.

**5. A configuration template with placeholders is committed; real configuration and secrets are git-ignored** (as in LogLens).

## Alternatives considered

**Hardcode per-instrument behaviour.** Rejected: does not scale and forces a code change per instrument.

**A single global configuration.** Rejected: instruments differ in channels, drift sensitivity, and location; one global blob cannot express that.

**Secrets in configuration, encrypted at rest.** Rejected: the platform secret store is the correct boundary; rolling a bespoke secret-encryption scheme is unnecessary risk.

## Consequences

**What this buys us.** Declarative onboarding, auditable and versioned behaviour, and governed secrets — a single, consistent configuration philosophy across the whole system.

**What it costs.** A configuration schema to maintain and validate.

**Scope discipline (over-engineering guard).** Configuration covers what genuinely varies per instrument. It is **not** a general rules engine: the drift rule list (ADR-005) is structured but bounded, and config is not a place to grow a DSL.

**Coupling.** Binds instruments (ADR-007) to channels (ADR-001), bin schemas (ADR-003), and drift rules (ADR-005); secrets are resolved through the platform (ADR-010).

---

*Authorship: architecture and all design decisions by the author. Implementation is AI-assisted. This ADR records the reasoning; the code is the proof.*
