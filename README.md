# BinMoments

**Real-Time Distribution Fingerprinting & Anomaly Detection for IoT Streams**

BinMoments models any sensor measurement — scalar, vector, or tensor — as a set of scalar **channels**, summarizes each channel as a streaming, bitemporal histogram, reads *exact* statistical moments and entropy from it, and detects when an instrument drifts from its own normal — by distribution distance, not static thresholds. It is built Databricks-native (Delta, serverless Spark, Unity Catalog), while keeping all analytical logic as plain, storage-agnostic Python.

The data model captures scalar, vector, and tensor measurements uniformly; the current slice computes on scalar channels, with vector and tensor handling fenced as recorded extensions.

---

## Validated on Databricks

Given a 28-day temperature stream with a drift fault **injected on three days and hidden from the detector**, the detector — calibrated only on clean data — caught all three drift days and raised zero false alarms. The run *asserts* this, so it fails loudly if the claim ever breaks.

```
date         distance  verdict       injected?
-----------  --------  -----------   ---------
2024-06-26    0.570  normal
2024-06-27    3.345  ** DRIFT **   yes
2024-06-28    3.357  ** DRIFT **   yes
2024-06-29    3.313  ** DRIFT **   yes
2024-06-30    0.656  normal

injected drift days caught: 3/3     false alarms: 0
VALIDATED on Databricks: every injected drift day caught, zero false alarms.
```

Because the anomaly is injected by a simulator that keeps the ground truth *separate* from the data, "it works" is a measured result, not a claim. You can reproduce it yourself — see **[docs/RUNBOOK.md](docs/RUNBOOK.md)** (a one-minute local check with `pytest`, or the full Databricks run).

---

## How it works, in one breath

Each scalar **channel** of a measurement is summarized per instrument-hour as a **variable-width, equal-mass histogram** (resolution follows the data). **Exact moments** (mean, variance, skewness, kurtosis) come from additive **power sums**; **percentiles and entropy** come from the bins. Increments are stored in an **append-only bitemporal fact** (valid time vs. transaction time), so any past state is reproducible under late data and corrections. **Drift** is detected by **Wasserstein distance** between an instrument's current distribution and a baseline of its own past, with a **self-calibrated** threshold per instrument.

---

## Everything is incremental

No statistic is ever recomputed from scratch. Each arriving measurement *adds* to a small set of running totals — the power sums behind the moments, and the histogram bin counts behind percentiles and entropy. Both are **additive**: combining two periods is just adding their totals. So a fingerprint for an arbitrary window — a day, a month, a full year — is assembled by summing the relevant increments, never by re-reading the raw data. The same additivity that makes this cheap is also what lets the work distribute across a cluster and reconstruct any past state (see the [mathematical companion](docs/companion/) for the proof).

---

## Design & reasoning

The decisions are the point; the code is the proof. Depth lives in three registers:

- **[docs/adr/](docs/adr/)** — the Architecture Decision Records: every decision, its alternatives, and its consequences (including decisions the build *reversed* on evidence).
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — a fuller technical overview of the system and its signature decisions.
- **[docs/book/](docs/book/)** — a narrative, listen-while-walking walkthrough of the whole system, chapter by chapter.
- **[docs/companion/](docs/companion/)** — the mathematical companion (the project's origin: it started from the math). *Written last, on purpose.*

---

## A deliberate companion to LogLens

This is the second of a deliberately contrasting pair. [LogLens](https://github.com/solar-mkd/ai-log-intelligence-platform) is built to be **platform-agnostic**; BinMoments is built to be **platform-native** (Databricks). The pairing is the point: it demonstrates judgment about *when* to embrace a platform and when to stay portable — and BinMoments keeps that honest by quarantining all analytical logic in storage-agnostic Python, with the platform-specific code confined to thin notebooks.

---

## Repository layout

```
docs/adr/         Architecture Decision Records (the design)
docs/book/        Narrative walkthrough, chapter by chapter
docs/companion/   Mathematical companion (Math-Companion-to-BinMoments) — the math origin
docs/RUNBOOK.md   How to run and verify, locally or on Databricks
src/binmoments/   The package — all analytical logic, plain testable Python (numpy)
notebooks/        Thin Databricks entry points that import the package
tests/            Local tests (run with pytest, no cluster needed)
```

---

## Authorship

The architecture, data-platform design, and all engineering decisions are the author's own. The implementation is AI-assisted — code generated against the documented architecture and decisions. The project's intent is to demonstrate data-architecture thinking: the design, the trade-offs, and the recorded reasoning. The ADRs are the point; the code is the proof.

---

## Status

The temperature vertical slice is **built, tested (50+ tests), and validated end-to-end on Databricks Free Edition** — including the drift detection above and the as-of reproducibility of the bitemporal fact. Future channels and capabilities are deliberately fenced as designed-for ADRs (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)); drawing that line is a scope decision, not an omission.
