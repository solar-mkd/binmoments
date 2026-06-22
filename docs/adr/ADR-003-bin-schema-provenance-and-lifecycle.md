# ADR-003 — Bin Schema Provenance & Lifecycle

**Status:** Accepted
**Context layer:** Statistical core — schema governance (how the derived bin schema is frozen, identified, versioned, and refit over time)
**Depends on:** ADR-001 (Measurement & Channel Model); ADR-002 (Bin Derivation Method) — this ADR governs the lifecycle of the artifact ADR-002 derives.
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

ADR-002 makes bin edges (and the value-axis transform) **data-derived** rather than universal constants. That single fact creates a governance problem the streaming model is acutely sensitive to.

Streaming histograms work because counts are **additively mergeable** — combining two time windows is summing their bin counts. But that is only valid when both windows were binned by the *same* edges. Two schemas with different edges place mass differently; summing their counts is meaningless. Worse, it fails **silently** — the addition still produces numbers, just wrong ones — which would quietly corrupt every downstream moment, percentile, and drift score with no error to catch it.

Two more facts follow from data-derived edges. A brand-new instrument has **no history** to derive a schema from — a cold-start problem. And a schema fitted once goes **stale**: climate shifts over years, instruments age and their characteristics drift, so edges fitted in one era will misplace mass in a later one.

A derived schema must therefore be treated as a **managed, versioned artifact** with a defined lifecycle — not as an implicit constant baked into code.

## Decision

**1. A bin schema is a frozen, versioned artifact identified by `bin_schema_id`.** The artifact comprises the bin edges and the value-axis transform together (everything ADR-002 derives). Every stored bin count is tagged with the `bin_schema_id` that produced it. **Counts are merged only within a single `bin_schema_id`, never across versions.** This is what makes the additive-merge property safe: the system can sum counts freely inside a version and is structurally prevented from summing across versions.

**2. Schemas are fitted per instrument *type* as the default, with a per-instrument override once an instrument has accumulated its own year of history.** A new instrument with no history inherits its type's schema — the cold-start solution, so it can be binned from day one. A mature instrument graduates to a schema fitted on its own data, for accuracy matched to its actual distribution. **Graduation mints a new `bin_schema_id`** and is a versioned, non-mergeable boundary like any other schema change.

**3. Schemas are refit on a stated cadence — annually, from a trailing 12-month window — and each refit mints a new version.** A schema is a dated artifact. Annual refit keeps edges matched to the current process and **absorbs legitimate new extremes**: a record-breaking reading lands in overflow this year (correctly flagged as unprecedented, per ADR-002's overflow policy) and is folded into next year's range so it is no longer anomalous. This couples the lifecycle directly to ADR-002's overflow-boundary decision.

*(This is the same provenance discipline LogLens applied to embedding vectors in its ADR-011/012 — pin the producer, version the artifact, keep versions separable — here applied to bin schemas. A consistent through-line: anything derived from data is versioned by what derived it.)*

## Alternatives considered

**Unversioned, globally-fixed universal schema** (one schema for all instruments, never refit). Trivially mergeable and simple. Rejected on two counts: it is blind to per-instrument distribution differences (a sensor in a cold climate and one in a hot climate forced onto the same edges, both placed badly), and blind to multi-year drift in the underlying process. It also offers no protection if edges ever *are* changed — merges would corrupt silently. The gain (no bookkeeping) is not worth the accuracy and safety lost.

**Per-instrument schemas from day one, with no type default.** Maximally accurate in principle. Rejected as the *default* because it has no cold-start answer: a new instrument could not be binned at all until it had accumulated a year of its own data. Per-instrument is retained as the *override* for mature instruments, not as the starting point.

**Version, but never refit.** Avoids the refit machinery. Rejected: without refit the schema rots — edges fitted years ago progressively misplace mass as the process drifts, and genuine new extremes never get absorbed into the normal range, so overflow fills with readings that are no longer truly unprecedented.

**Recompute edges on the fly / per window.** Rejected at the schema level for the same reason ADR-002 rejects per-window value-axis rescaling: it destroys both mergeability and cross-window comparability. Edges must be stable to be summable.

## Consequences

**What this buys us.** Safe streaming merges (only within a version). Per-instrument accuracy for mature instruments, with a clean cold-start path for new ones via type inheritance. Resilience to multi-year drift through periodic refit. And a coherent novelty signal, because the overflow boundary and the refit cadence work together rather than fighting each other.

**What it costs.** Lifecycle machinery: schemas must be fitted, frozen, assigned a `bin_schema_id`, stored, and refit on cadence; every count must carry its `bin_schema_id`; cross-version merges must be actively prevented. This is real complexity — but it is *necessary* complexity, not gold-plating. Without versioning, the additive-merge property breaks silently and corrupts every downstream statistic. The alternative is not "simpler," it is "wrong."

**Scope discipline (over-engineering guards).**
- The initial slice fits **per-instrument directly** — it has its training year in hand — so the **type-default and inheritance path is the cold-start mechanism, built when the first history-less instrument is actually onboarded**, not on spec.
- The refit cadence is recorded as **policy**; an automated refit scheduler is a later operational concern, not part of the vertical slice. The slice fits once and freezes.
- Versioning is implemented from the start (it is cheap — an id column and a merge guard) and earns its place immediately, because even the slice's single refit or per-instrument graduation would otherwise risk a silent cross-version merge.

**Coupling to later decisions.** The bitemporal increment fact (ADR-004) stores every count tagged with `bin_schema_id`. *Merging* counts happens only within a single `bin_schema_id` — that prohibition is absolute. *Comparison* across versions (the drift metric comparing an instrument to its own prior year) is still possible, but not by merging: both histograms are resampled onto a common fixed grid (ADR-016) and compared there. The distinction is the key to reconciling this ADR's hard merge boundary with ADR-005's year-over-year requirement — a schema change blocks summation, not comparison.

---

*Authorship: architecture and all design decisions by the author. Implementation is AI-assisted — code generated against the documented architecture and decisions. This ADR records the reasoning; the code is the proof.*
