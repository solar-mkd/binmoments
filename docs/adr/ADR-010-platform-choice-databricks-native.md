# ADR-010 — Platform Choice: Databricks-Native Lakehouse

**Status:** Accepted
**Context layer:** Cross-cutting platform decision (the runtime the whole system is built on, and why)
**Depends on / realizes:** ADR-004 (streaming + as-of storage), ADR-003 (versioned artifacts), ADR-007 (governed reference data).
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

BinMoments is, by deliberate design, the **platform-native** counterpart to LogLens. LogLens was built storage- and scheduler-agnostic on purpose, with portability as an architectural value. BinMoments takes the opposite stance on purpose: it commits to a specific lakehouse platform and leans on its distinctive capabilities, so the two projects together demonstrate *both* competences — designing for portability, and designing to exploit a platform. This ADR records the choice as a defensible decision with its trade-offs, not as an assumption.

## Decision

**1. Build on the Databricks lakehouse:** Delta Lake (ACID storage, time travel), Structured Streaming (the streaming histogram aggregation), Unity Catalog (governance, lineage, access control), and Databricks compute for batch, streaming, and the later ML extension.

**2. The defensible reasons, tied to specific earlier decisions:**
   - **Structured Streaming** provides stateful streaming aggregation with watermarking and exactly-once semantics — a direct fit for streaming bin increments and for handling late data alongside the bitemporal model of ADR-004.
   - **Delta Lake** gives ACID append-only writes and time travel — matching the increment fact's append-only requirement, and complementing (not replacing, per ADR-004) the explicit bitemporal columns.
   - **Unity Catalog** gives native lineage and governance — directly serving the reproducibility and audit story (ADR-004) and the governed instrument metadata (ADR-007).
   - **One platform** for streaming + batch + ML (the forecasting extension, ADR-012) + BI reduces the integration surface to near zero.

**3. The analytical logic stays platform-agnostic where it costs nothing to do so.** Bins, moments, and drift are pure PySpark/Python computations; the *reasoning* remains portable even though the *deployment* is Databricks-native. Native where it pays (streaming, storage, governance), agnostic in the pure logic.

## Alternatives considered

**Self-managed Spark + object store.** Rejected: heavier operational burden and no native governance/lineage — it would reinvent what Unity Catalog provides.

**The LogLens stack (local PostgreSQL + pgvector).** Rejected *on purpose*: this project exists to demonstrate platform-native lakehouse architecture; reusing LogLens's stack would duplicate it and forfeit the deliberate contrast between the two projects.

**Cloud-native managed services (separate streaming + warehouse).** A viable path. Databricks was chosen for the **unified** lakehouse — streaming, batch, ML, and governance in one place — which matters precisely because this system spans all four.

## Consequences

**What this buys us.** Native streaming and governance that several earlier decisions assume; a single platform for the system's full span; and a portfolio narrative — one portable project, one platform-native project — that is itself a signal of range.

**What it costs.** Platform lock-in, a real and acknowledged trade — the deliberate inverse of LogLens's portability. Plus the platform's cost model and reduced low-level control. Stated openly, not hidden.

**Scope discipline (over-engineering guard).** Use the native features that pay their way (Structured Streaming, Delta, Unity Catalog). Do **not** reach for Databricks features for their own sake — notably, Vector Search is *not* adopted, because ADR-005 already established the core needs no vector store.

---

*Authorship: architecture and all design decisions by the author. Implementation is AI-assisted. This ADR records the reasoning; the code is the proof.*
