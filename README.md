# BinMoments

**Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams**

An architecture-led platform that summarizes each IoT sensor channel as a streaming,
bitemporal histogram, derives statistical moments and entropy from it, and detects when an
instrument drifts from its own normal — using distribution distance rather than threshold
banding. Built Databricks-native (Structured Streaming, Delta, Unity Catalog).

> **Status: in progress.** The architecture is complete and recorded as ADRs (see
> `docs/adr/`); implementation is being built as a thin vertical slice first. This README
> describes the design; the code is being filled in behind it.

> **Authorship.** The architecture, data-platform design, and all engineering decisions are
> the author's own. The implementation is AI-assisted — code generated against the documented
> architecture and decisions. The project's intent is to demonstrate data-architecture
> thinking: the design, the trade-offs, and the recorded reasoning. The ADRs are the point;
> the code is the proof.

---

## The problem

A fleet of IoT instruments emits floods of measurements. The operational question is rarely
"what is the latest value" but "is this instrument's *behaviour* changing — and can I prove
what I knew when I made a decision?" Answering that needs three things most pipelines skip:
a faithful statistical summary at controlled accuracy, reproducibility of past state under
late-arriving data and corrections, and a drift signal that catches distributional change a
static threshold misses.

## The idea

Each scalar **channel** of a measurement (a tensor decomposed into magnitude + direction, so
scalars, vectors, and tensors all reduce to scalar channels) is summarized per instrument-hour
as a **variable-width, equal-mass histogram**. From those bins the system derives moments,
entropy, and percentiles; stores increments in an **append-only bitemporal fact** (valid time
vs. transaction time) so any past state is reproducible; and detects **drift** by Wasserstein
distance between an instrument's current distribution and a baseline of its own past.

## Signature decisions

A few of the most consequential; the full set is in [`docs/adr/`](docs/adr/).

- **Variable-width, equal-mass bins** (ADR-002) — resolution follows the data, so tail
  percentiles and anomalies are well resolved; fixed-width binning is rejected.
- **Frozen, versioned bin schemas** (ADR-003) — data-derived edges are pinned per
  `bin_schema_id`; counts never merge across versions, the same provenance discipline applied
  to embeddings in the companion project.
- **Bitemporal increment fact** (ADR-004) — append-only signed deltas with valid and
  transaction time; late data and corrections never overwrite history, so "what I saw
  yesterday, and how it changed" is a first-class query.
- **Wasserstein drift, cosine rejected** (ADR-005) — distributions are compared directly;
  a hand-crafted moment vector with cosine distance is rejected because it conflates a level
  shift with a shape change.
- **Cross-schema comparison by CDF resampling** (ADR-016) — year-over-year comparison across a
  schema refit resamples both CDFs onto a common grid, so comparison is enabled without ever
  merging counts across versions.
- **Moments from bins, with a generalized Sheppard correction** (ADR-006) — the histogram is
  the single source of truth; grouped-moment bias is corrected with a mass-weighted, variable-
  width generalization of Sheppard's corrections.

## Architecture overview

Sources -> **Bronze** (raw landing, identity, idempotency) -> **Silver** (parse, normalize to
channels, resolve late data/corrections to signed deltas) -> **Gold** (bitemporal binned
increment fact, moment/entropy materializations, drift signals). Reference data — the
instrument registry with geodetic location (datum + epoch) and labels — joins in silver.
See ADR-009 (layering), ADR-007 (registry), ADR-010 (platform).

## Repository layout

```
docs/adr/        Architecture Decision Records (the design)
docs/companion/  Companion document & math appendices (Sheppard derivation, precision proof)
src/binmoments/  The package — all logic, plain testable PySpark
notebooks/       Thin Databricks entry points that import the package
tests/           Local tests (run with pytest, no cluster needed)
config/          Per-instrument config (template committed; real config git-ignored)
```

## Getting started

See [`docs/SETUP.md`](docs/SETUP.md). In short: create a venv, `pip install -r requirements.txt`
and `pip install -e .`, then `pytest`.

## Designed-for, not built

Deliberately fenced as future extensions, with their designs recorded: forecasting on the
fingerprint (ADR-012), cross-measurement correlation mining (ADR-013), cross-instrument
similarity & vector search (ADR-014), rank-2 tensor support (ADR-015), and a general
user-composed rule engine (ADR-017). Fencing these is a scope decision, not an omission.
