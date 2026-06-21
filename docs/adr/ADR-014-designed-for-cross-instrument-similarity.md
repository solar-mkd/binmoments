# ADR-014 — Designed-For: Cross-Instrument Similarity & Vector Search

**Status:** Designed-for (not built)
**Context layer:** Future extension (grouping instruments by distribution shape across a fleet)
**Depends on:** ADR-006 (fingerprint vector), ADR-005 (which scoped drift as intra-instrument and removed vector search from the core).
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

The original idea included grouping instruments by their statistical distribution — finding instruments
that behave alike across a fleet. ADR-005 scoped the **core** drift capability as intra-instrument (each
instrument against its own past) and, as a direct consequence, removed any vector database from the core:
drift is a scalar time series, not a nearest-neighbour problem. This ADR records cross-instrument
similarity as the **designed-for** case — the one place where a vector store would legitimately return —
with its right-sizing decision attached.

## Decision (deferred)

If cross-instrument similarity / clustering is needed, it uses the **fingerprint vector (ADR-006),
standardized across the population** (z-score or robust scaling), compared by **Euclidean or Mahalanobis
distance — not cosine** (for the level-vs-shape and collinearity reasons established in ADR-005), and — if
a vector index is warranted — **Databricks Vector Search, not pgvector** (vector search was already proven
in LogLens; repeating it adds nothing, and the Databricks-native stance of ADR-010 applies).

**Right-sizing rule:** below a fleet of many thousands of instruments, brute-force standardized-distance
in Spark is sufficient and a vector store is over-engineering. A vector index is adopted only when fleet
size actually demands ANN.

**Trigger to build:** a real need to compare across a sizeable fleet — which does not exist until there is
a fleet.

## Alternatives noted

Cosine on the raw fingerprint is rejected (ADR-005's conflation of level and shape; collinear percentiles).
pgvector is rejected (repeats LogLens; contradicts ADR-010). Building before a fleet exists is rejected —
the core is intra-instrument; cross-instrument is speculative until there is something to compare.

## Consequences

Deferred; the fingerprint is deliberately designed to support it (standardize → Euclidean/Mahalanobis) if
needed. Fence: not built, and right-sized — brute force before any vector index.

---

*Authorship: architecture by the author; implementation AI-assisted. This ADR records a deferred decision.*
