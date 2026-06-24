# Production Readiness

**How BinMoments is designed to meet production obligations — and what is deliberately deferred.**

---

## The register of this document

BinMoments is a validated vertical slice, not a production deployment. This document describes how the architecture is *designed* to meet production obligations — service levels, recovery, governance, audit — and is explicit about which properties are already demonstrated, which follow directly from design choices, and which are deliberately deferred. It is a readiness and reasoning document: its purpose is to show that these concerns were treated as first-class architectural inputs, not retrofitted afterthoughts. Where a claim is proven, it says so; where it is a design intention, it says that too.

A note on what makes this credible: several of these obligations have *specific* answers rooted in design decisions already made and recorded — the bitemporal append-only fact (ADR-004), frozen versioned bin schemas (ADR-003), the storage-agnostic analytical core (ADR-010), and the validated distributed aggregation (ADR-010). Those are not generic checklist answers; they are properties of this system. The remainder are honest statements of awareness with a deferred status.

---

## Service levels (SLA / SLO)

**Obligation.** Define what "working" means in measurable terms — freshness, availability, and correctness of the drift signal — so that degradation is detectable rather than discovered by a missed anomaly.

**Design.** The natural service-level objectives for this system are: *freshness* (a fingerprint for instrument–hour H is available within a bounded lag after H closes, accounting for the late-data horizon); *availability* of the drift query (the gold tables are readable); and *detection correctness* (recall on injected/known faults and a bounded false-alarm rate, the two halves the validation already scores). Because fingerprints are assembled from additive increments, freshness degrades gracefully — a late batch updates totals without forcing a full recompute.

**Status.** Detection correctness is *demonstrated* on the validation slice (3/3 injected drift days caught, zero false alarms). Freshness and availability targets are design intentions; they are not yet measured under load or expressed as monitored SLOs.

---

## Recovery objectives (RPO / RTO)

**Obligation.** State the tolerable data loss (Recovery Point Objective) and tolerable downtime (Recovery Time Objective), and design storage so they can actually be met.

**Design.** The bitemporal, append-only fact (ADR-004) is a genuine recovery asset. Raw readings land in an immutable bronze layer, and the increment fact records signed deltas in valid time (event hour) versus transaction time (arrival), so **no past state is ever overwritten** — corrections are compensating entries, not edits. This means:
- **RPO** is bounded by the durability of the bronze landing and the increment log: anything durably landed is recoverable, and because corrections are additive rather than destructive, a bad correction does not lose the prior truth — it can be reconstructed as-of any earlier transaction time.
- **RTO** for the analytical layer is short by construction: the analytical logic is stateless, storage-agnostic code (ADR-010), so recovering it is redeploying the package; only the Delta tables are stateful, and they are managed and replayable.

**Status.** These are architectural properties of the design (as-of reconstruction is *demonstrated* in the bitemporal tests); concrete RPO/RTO *targets* and a rehearsed failover have not been set or exercised on real infrastructure.

---

## Disaster recovery (DR)

**Obligation.** Survive the loss of a region, a workspace, or a storage layer with a defined path back to service.

**Design.** DR rests on three properties already in the design. First, **immutability**: bronze and the increment fact are append-only, so recovery is replay, not repair. Second, **separation of logic from state**: the analytical core carries no state (ADR-010), so it can be stood up anywhere the package runs — laptop, a second workspace, another platform — which the project demonstrates by running the identical logic locally and on Databricks. Third, **reconstructability**: every gold artifact (fingerprints, drift signals) is a deterministic function of the additive increments, so gold can be rebuilt from bronze without re-deriving anything by hand.

The intended DR posture is therefore: protect bronze and the increment log as the source of truth (replication / cross-region copy), and treat everything downstream as rebuildable.

**Status.** Design intention. Cross-region replication and a documented, timed recovery runbook are deferred; the reconstructability they rely on is real and tested.

---

## Backup & point-in-time recovery

**Obligation.** Be able to restore the system to a known-good earlier state.

**Design.** Point-in-time recovery is partly *intrinsic* here rather than bolted on. The Delta format provides table-level time travel; the bitemporal fact adds a second, semantic time axis, so the system can answer not only "what did the table contain at version N" but "what did we *know* about instrument I as-of transaction time T" — the stronger, audit-grade form of point-in-time. The backup surface is also small and well-separated: the **analytical layer has nothing to back up** (it is code in version control), so backup scope is exactly the Delta state — bronze, the increment fact, the instrument registry, and the frozen bin schemas.

**Status.** The mechanisms (Delta time travel, append-only history, content-hashed schema provenance) are in the design and partly demonstrated; a scheduled backup/retention policy and restore drills are deferred.

---

## Scalability

**Obligation.** Show the system scales from one instrument to a fleet, and from a slice of data to production volumes, without re-architecture.

**Design — and the one section that stands on proof.** The analytical moments are computed from **additive power sums**, chosen so they distribute as ordinary Spark aggregations (`count`, `sum(value^k)`) across partitions and combine across them. This was *validated on Databricks*: the moments computed as a single-machine reference and as a distributed Spark aggregation over the same Delta table **matched to floating-point precision**. The same additivity that gives bitemporal reproducibility gives distribution for free; the histogram counts distribute by the identical principle. So scaling to many instruments and large volumes is a property of the math, not a hopeful claim — and it has been exercised, not just asserted.

**Status.** *Demonstrated* for the moments (distributed aggregation matches reference exactly). Distributing the binning counts is fenced as the same-principle extension (ADR-010); large-volume and high-cardinality load testing is deferred.

---

## Data governance

**Obligation.** Control over data definitions, ownership, access, and lineage — so the numbers mean the same thing over time and across teams.

**Design.** Two mechanisms carry this. **Unity Catalog** provides the governance substrate — a named catalog/schema, ownership, and access control over the tables (ADR-010). And the **frozen, versioned, content-hashed bin schemas** (ADR-003) give analytical lineage: a `bin_schema_id` is derived from the schema's content, never reused across versions, and counts are never merged across versions. That means any fingerprint is traceable to the exact binning definition that produced it, and a re-fit is automatically a new, distinguishable lineage — a provenance discipline that prevents silently comparing incomparable distributions.

**Status.** The schema-provenance mechanism is *built and tested*. Catalog-level ownership, classifications, and access policies are design intentions resting on Unity Catalog; they are not configured on the validation slice.

---

## Auditability & lineage

**Obligation.** Reconstruct, after the fact, what the system reported, on what data, and what changed.

**Design.** Auditability is a direct consequence of the bitemporal fact (ADR-004). Because the increment log is append-only and carries both valid time and transaction time, the system holds a complete record of *what was known, and when* — including how a value changed, since corrections appear as explicit compensating entries rather than overwrites. Combined with the content-hashed schema provenance (ADR-003), every reported statistic is traceable end-to-end: from the drift verdict, to the fingerprint, to the bin schema, to the immutable readings and the exact as-of state. There is no step where the trail is broken by an in-place edit.

**Status.** The underlying record (append-only bitemporal history, schema provenance) is *built and tested* — as-of reconstruction is exercised directly. Operational audit tooling (access logs, query attribution, retention of audit views) is deferred to a real deployment.

---

## Security & access

**Obligation.** Protect data confidentiality and integrity, and control who can read or change what.

**Design.** Confidentiality and access control are intended to be delegated to the platform — Unity Catalog for table-level grants and the workspace's identity and secret management for credentials (ADR-011 covers config and secrets, with real secrets kept out of version control). Integrity is reinforced by the append-only design: there is no in-place mutation path for historical facts, which narrows the surface for silent tampering.

**Status.** Design intention. Concrete access policies, secret-manager integration, and encryption posture are platform configuration not set on the validation slice; the integrity-by-immutability property is real.

---

## What is deliberately not yet implemented

Stating this plainly is part of the readiness, not a gap in it:

- **Measured SLOs under load** — freshness/availability targets are designed, not monitored.
- **Rehearsed failover and timed RTO** — the reconstructability is real; the drill is not done.
- **Cross-region replication and scheduled backups** — the recovery *properties* exist; the operational policy does not.
- **Large-volume / high-cardinality load testing** — scaling is proven for the moments at slice scale; production-scale testing is deferred.
- **Configured access, classification, and encryption policies** — the governance *substrate* (Unity Catalog) is chosen; the policies are not provisioned.

Each of these is an operational provisioning task on top of an architecture that was designed to accommodate it — which is the distinction this document exists to make. The design treats production obligations as inputs; turning them on is deployment work, and it is named here rather than implied.

---

*BinMoments — Production Readiness. A design-and-readiness document: proven where it says proven, intended where it says intended.*
