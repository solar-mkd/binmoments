# BinMoments — Architecture Overview

**Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams**

This is the fuller technical companion to the [top-level README](../README.md). It describes the problem, the core idea, the signature decisions, the medallion architecture, and the validation methodology. The complete decision record is in [`docs/adr/`](adr/); a narrative walkthrough is in [`docs/book/`](book/).

> **Authorship.** The architecture, data-platform design, and all engineering decisions are the author's own. The implementation is AI-assisted — code generated against the documented architecture and decisions. The intent is to demonstrate data-architecture thinking: the design, the trade-offs, and the recorded reasoning. The ADRs are the point; the code is the proof.

---

## The problem

A fleet of IoT instruments emits floods of measurements. The operational question is rarely "what is the latest value" but "is this instrument's *behaviour* changing — and can I prove what I knew when I made a decision?" Answering that needs three things most pipelines skip: a faithful statistical summary at controlled accuracy, reproducibility of past state under late-arriving data and corrections, and a drift signal that catches distributional change a static threshold misses.

## The idea

Each scalar **channel** of a measurement (a tensor decomposed into magnitude + direction, so scalars, vectors, and tensors all reduce to scalar channels) is summarized per instrument-hour as a **variable-width, equal-mass histogram**. From those bins the system derives percentiles and entropy; it computes exact statistical moments from additive power sums; it stores increments in an **append-only bitemporal fact** (valid time vs. transaction time) so any past state is reproducible; and it detects **drift** by Wasserstein distance between an instrument's current distribution and a baseline of its own past.

## Signature decisions

A few of the most consequential; the full set is in [`docs/adr/`](adr/).

- **Variable-width, equal-mass bins** (ADR-002) — resolution follows the data, so tail percentiles and anomalies are well resolved; fixed-width binning is rejected. A year of Brisbane temperature, binned this way, places sub-degree bins in the crowded daytime range and wide bins out in the rare extremes — every bin carrying equal mass.

- **Frozen, versioned bin schemas** (ADR-003) — data-derived edges are pinned by a content-hash `bin_schema_id`; counts never merge across versions. Re-deriving from the same data yields the same id (reproducible); a refit on new data yields a new id automatically (versioned). The same provenance discipline LogLens applied to embeddings.

- **Bitemporal increment fact** (ADR-004) — append-only signed deltas with valid and transaction time; late data and corrections never overwrite history, so "what I saw yesterday, and how it changed" is a first-class query. Corrections are compensating deltas (retract the old reading, assert the new), never edits.

- **Exact moments from additive power sums** (ADR-006) — moments (mean, variance, skewness, kurtosis) are computed *exactly* from running power sums (`n, Σx, Σx², Σx³, Σx⁴`), **not** from bin midpoints. This decision was *reversed during the build*: numerical validation showed the original bin-midpoint-plus-Sheppard approach overestimated variance by 5–90% on equal-mass bins, because wide tail bins place their midpoint far from where the mass actually sits. Power sums are exact, additive (so they ride the bitemporal rails and distribute across Spark partitions for free), and they restore the author's original instinct. Bins remain the right tool for percentiles, entropy, and drift.

- **Wasserstein drift, cosine rejected** (ADR-005) — distributions are compared directly; a hand-crafted moment vector with cosine distance is rejected because it conflates a level shift with a shape change. Wasserstein distance is also expressed in the value's own units (a 5° shift reads as a distance of ~5). Thresholds are self-calibrated per instrument from its own normal scatter, not set by a global magic number.

- **Cross-schema comparison by CDF resampling** (ADR-016) — year-over-year comparison across a schema refit resamples both CDFs onto a common fixed grid (built on the fly, nothing stored), so comparison is enabled without ever merging counts across versions. The same shared-ruler mechanism is what a future cross-instrument (spatial) comparison would use.

## The fingerprint

Each instrument-hour is summarized as a fingerprint vector: `[mean, variance, skewness, kurtosis, p50, p90, p95, p99, entropy]`. It is sourced from two structures, each doing what it is best at: the **moments** from exact power sums (no binning bias), the **percentiles and entropy** from the equal-mass bins (where the distribution shape lives). Entropy carries a clean interpretation under the equal-mass schema — the historical reference sits at maximum entropy, so a *concentrating* distribution registers as an entropy drop.

## Drift detection and validation

Drift is intra-instrument: each instrument is compared to its own past, never to a global standard or (yet) to its neighbours. The primary signal is the Wasserstein distance from the current window's distribution to a baseline distribution, against a self-calibrated threshold. This signal is excellent at **level** drift — a shift in where the mass sits — and reports it directly in the variable's units.

A **pure spread change at a stable mean** (variance grows, centre fixed) is the primary signal's known soft spot: it transports little mass, so the daily Wasserstein stays quiet. This is a boundary, not a blind spot — the change is fully present in the **fingerprint** (its `variance` component moves even when `mean` does not), and two designed-for mechanisms read it there: a **complementary variance-moment signal** that watches the variance against its own normal, and the fenced **Mahalanobis second opinion** (ADR-005) that scores the whole fingerprint vector against the instrument's history and can say *which* moment moved. In the current slice these are designed-for, not wired into the daily detector, so pure-spread faults are detected by the fingerprint but not flagged by the slice's drift check. This is characterized empirically — caught level shifts, the detection floor, and the spread soft spot — in the [experiment log](experiments/simulation-results.md).

Validation is by **ground truth**. The synthetic simulator (ADR-008) injects known faults into the readings while keeping a separate ground-truth log; the detector runs on the readings alone and is scored against that log — recall (did it catch the injected drift) and precision (did it stay quiet on clean stretches). Across the scenario suite the level-shift faults are caught with zero false alarms, the small sub-threshold shift is correctly not chased, the variance fault is the documented soft spot, and a fixed baseline run across seasons reproduces the seasonality failure the seasonal baseline (ADR-005) prevents — all recorded in the [experiment log](experiments/simulation-results.md).

## Scaling

The analytical moments run as **Spark-native aggregations** (`count`, `sum(value^k)`) that distribute across partitions and combine across them — feasible *because* the power sums were chosen additive (ADR-006/ADR-010). This was validated by computing the moments both as a single-machine reference and as a distributed Spark aggregation over the same Delta table, and confirming the results match to floating-point precision. The same additivity that gives bitemporal reproducibility gives distribution for free; the binning counts distribute by the identical principle (implementation deferred — a deliberate scope line, not a gap).

## Serving: materialized current state

Reading the "current" histogram by summing the whole append-only fact on every query is wasteful at scale. A derived, rebuildable **current-state read model** (ADR-020) is maintained by Delta `MERGE` — collapsed to one net count per (instrument, schema, bin), including all corrections — so the latest distribution is a single keyed read. It is a cache, never a source of truth: it is always reconstructable from the fact, and a consistency check asserts the incrementally-maintained table equals a full rebuild. The per-hour `histogram` table serves the time-resolved view; both are derived projections alongside the unchanged write model (an event-sourcing / CQRS shape).

## Architecture overview

Sources → **Bronze** (raw landing, identity, idempotency) → **Silver** (parse, normalize to channels, resolve late data/corrections to signed deltas) → **Gold** (bitemporal binned increment fact, moment/entropy materializations, drift signals). Reference data — the instrument registry with geodetic location (datum + epoch) and labels — joins in silver. See ADR-009 (layering), ADR-007 (registry), ADR-010 (platform). All analytical logic is plain, storage-agnostic Python (numpy); the Spark and Delta code is confined to thin notebooks, so the logic is fully testable locally without a cluster.

## Repository layout

```
docs/adr/         Architecture Decision Records (the design)
docs/book/        Narrative walkthrough, chapter by chapter
docs/companion/   Mathematical companion (Math-Companion-to-BinMoments) — the math origin
docs/production/  Production-readiness: SLA, RPO/RTO, DR, governance, auditability
docs/experiments/ Simulation results: the detector characterized across scenarios
docs/RUNBOOK.md   How to run and verify, locally or on Databricks
src/binmoments/   The package — all analytical logic, plain testable Python (numpy)
notebooks/        Thin Databricks entry points that import the package
tests/            Local tests (run with pytest, no cluster needed)
```

## Built vs. designed-for

**Built and validated** (the temperature vertical slice): the channel/measurement model (ADR-001), the ground-truth simulator (ADR-008), equal-mass binning (ADR-002/003), the bitemporal fact (ADR-004), the power-sum fingerprint (ADR-006), drift detection (ADR-005) with the cross-schema grid (ADR-016), static value-band classification (ADR-017), and the materialized current-state read model (ADR-020), all running on Databricks.

**Designed-for, not built** — deliberately fenced as future extensions, with their designs recorded: forecasting on the fingerprint (ADR-012), cross-measurement correlation mining (ADR-013), cross-instrument similarity & vector search (ADR-014), rank-2 tensor support (ADR-015), spatial-coherence anomaly detection across nearby instruments (ADR-018), zero-inflated / heavy-tailed channels such as rainfall (ADR-019), the complementary variance-moment and Mahalanobis drift signals (ADR-005), and a general user-composed rule engine (the fenced half of ADR-017). Fencing these is a scope decision, not an omission — each is a captured idea with a trigger to build, not a vague aspiration.

## A deliberate companion to LogLens

BinMoments is the second of a contrasting pair. [LogLens](https://github.com/solar-mkd/ai-log-intelligence-platform) is built deliberately **platform-agnostic**; BinMoments is built deliberately **platform-native** (Databricks: Delta, serverless Structured Streaming, Unity Catalog). The contrast demonstrates judgment about *when* a platform commitment pays for its lock-in and when portability is worth more — and BinMoments keeps that distinction principled by isolating all analytical logic in storage-agnostic Python, embracing the platform only where it pays (storage, streaming, governance, distribution).
