# ADR-005 — Drift Detection: Distribution Distance & Baseline Policy

**Status:** Accepted
**Context layer:** Analytical core — the headline anomaly-detection capability (how the system decides an instrument has drifted from its own normal)
**Depends on:** ADR-001 (channels; `linear | circular` flag), ADR-002 (the histograms compared and their fixed value axis), ADR-003 (comparisons across versions cross a refit boundary), ADR-004 (comparisons use as-of-consistent snapshots), ADR-016 (cross-schema comparison grid for year-over-year comparison).
**Related:** ADR-017 (value-band classification computed alongside drift).
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

The headline capability of the system is detecting when an instrument's behaviour **drifts from its own normal** — an early signal that the instrument, or the process it measures, has changed and is worth inspecting before it fails or misleads. The raw material is already in place: per-`(instrument, channel, event_hour)` histograms (ADR-002/003), recorded bitemporally so any past state is reproducible (ADR-004). Drift detection is the act of **comparing an instrument's current distribution against a baseline of its own past** and raising a signal when the difference is large enough to matter.

Two questions have to be answered, and they are independent: *what distance* measures the difference between two distributions, and *against which baseline* is "current" compared.

The original design answered the first question with a hand-crafted **fingerprint vector** — `[mean, variance, skewness, kurtosis, p50, p90, p95, p99, entropy]` — compared by **cosine distance**. On inspection this does not measure what the system needs. The components have wildly different units and magnitudes (mean and the four percentiles are large and in the variable's units; variance, skewness, entropy are small), so the cosine angle is dominated by the level terms and is nearly blind to the *shape* change that is the actual point of drift detection. Worse, the four percentiles are strongly collinear with each other and with the mean, so the vector triple-counts "level" and barely represents shape at all. Cosine on this vector conflates "the level shifted" with "the shape changed" — and it is precisely a shape change at a stable level (a distribution spreading, growing tails, going bimodal) that signals an instrument going wrong. The fingerprint idea is not abandoned, but it is not the right tool for *temporal* drift; the right tool compares the distributions directly.

A second concern is **seasonality**. Temperature and most environmental quantities have strong daily and seasonal cycles. Comparing 14:00 against 02:00, or July against January, would raise drift alarms for entirely normal cyclic variation. The baseline policy must control for this.

## Decision

**1. Drift is intra-instrument: each instrument is compared only against its own past.** This is a scoping decision with large consequences — it removes any need for cross-instrument similarity search, and therefore any vector database. A drift signal is a **scalar time series per `(instrument, channel)`**, stored in plain Delta; no ANN index, no pgvector. (Reusing a vector store here would merely repeat LogLens without need.)

**2. The primary distance is the Wasserstein (earth-mover's) distance between the current and baseline histograms,** computed from the versioned variable-width bins (ADR-002). In one dimension this is the integral of the absolute difference of the two cumulative distributions, read directly from the cumulative bin counts and the bin edge positions — O(bins) and cheap. It requires the bin **values** (edge positions), not just counts, and **mass normalization** (each histogram summed to 1) on both sides, since Wasserstein is defined between distributions of equal total mass.

**3. The baseline is configurable per instrument as a list of drift rules.** A rule is a structured object: `{ baseline: previous_hour | same_hour_yesterday | rolling_window(n) | historical_reference, metric: wasserstein, threshold: <calibrated> }`. Multiple rules run simultaneously per instrument. `same_hour_yesterday` is the **seasonality control** — comparing 14:00 to the previous day's 14:00 removes the daily cycle — and is the recommended default for cyclic quantities. The seasonality problem is thus solved by *baseline choice*, not by a separate de-seasonalization mechanism. `historical_reference` compares against the instrument's all-time normal; because equal-mass bins make the training distribution uniform by construction (ADR-002), this baseline reduces to "how far has the current histogram moved from flat" — a cheap, clean reference.

**4. Thresholds are self-calibrated against each instrument's own historical distance distribution, not hand-set.** A rule fires when the current Wasserstein-vs-baseline exceeds, say, the instrument's own 99th-percentile historical value for that same comparison. Thresholds are always expressed in the metric's own terms (the variable's units), **never as a bare percentage** — "5% drift" is undefined for a distance that lives in degrees Celsius. Self-calibration avoids a magic number per instrument and adapts to each instrument's natural variability.

**5. Comparisons are as-of consistent. Same-version comparisons use native bins directly; cross-version comparisons resample onto a common grid first.** Drift is always evaluated between two reproducible snapshots (ADR-004), so "is it drifting" is asked against defensible distributions, not against counts that may have silently shifted under late data. When both histograms share a `bin_schema_id`, the Wasserstein distance is computed directly on the native variable bins (cheap, exact). When a comparison crosses a schema refit boundary (ADR-003) — which is exactly what `historical_reference` and any year-over-year baseline require — the two histograms have **different edges and cannot be compared bin-to-bin**; both are first resampled onto a common fixed grid via the cross-schema comparison procedure of **ADR-016**, and the distance is computed there. A schema change is thus a comparison **boundary that is bridged by resampling, not an impossibility** — resolving the otherwise-contradiction between ADR-003's "never merge across versions" (which forbids *summing* counts) and this ADR's need to *compare* across years (which only needs the distributions made commensurable, not merged).

**6. Static value-band classification (Nominal / Elevated / Warning / Critical) is computed alongside drift**, from per-instrument configured thresholds, and is recorded in ADR-017. It is a cheap, complementary signal — a familiar operational banding that sits next to the distribution-distance drift signal, not a replacement for it. A general user-composed rule engine over these bands is fenced as designed-for in ADR-017.

## Alternatives considered

**Cosine distance on a hand-crafted moment/percentile vector** (the original design). Rejected: the components' heterogeneous scales make cosine dominated by level and blind to shape, and the collinear percentiles triple-count level. It conflates a level shift with a shape change — and shape change at stable level is exactly the signal wanted. Comparing the distributions directly avoids hand-crafting and scaling a feature vector at all.

**Population Stability Index (PSI).** The industry-standard drift metric, computed straight from bin counts — a strong candidate, retained as a documented sibling (and covered in the companion appendix). Rejected as *primary* because it is a bin-wise sum of proportion changes that does not account for *how far* mass moved (a shift into an adjacent bin and a shift across the whole range can score similarly), and it is ill-behaved when a bin is empty on one side (terms blow up or require ad-hoc flooring).

**Jensen–Shannon divergence.** Principled, symmetric, bounded — also retained as a documented sibling. Rejected as primary because it **saturates** once the two supports barely overlap: a modest real shift and an enormous one both read near the maximum, destroying the "how far" information that makes drift *actionable* rather than merely *detectable*.

**Kolmogorov–Smirnov statistic.** The maximum gap between the two CDFs. Rejected: it captures the single largest point of divergence but not the total mass movement, so it is less informative than Wasserstein about the magnitude and extent of a shift.

**A vector database for drift** (storing fingerprints and searching). Rejected: intra-instrument drift is a scalar time series, not a nearest-neighbour problem. A vector store would add infrastructure for a capability the design does not need.

**Wasserstein was chosen** because it measures the actual cost of transporting mass from one distribution to the other: it captures *how far* the distribution moved, degrades gracefully when supports separate (no saturation), is naturally expressed in the variable's own units (directly interpretable, and the basis for self-calibrated thresholds), and is cheap to compute from the cumulative bin counts already maintained. The trade-off — it needs bin edge positions and is marginally more expensive than a bin-wise proportion sum — is small and worth it.

## Consequences

**What this buys us.** A principled, interpretable drift signal in the variable's own units; seasonality handled through baseline choice rather than a bolt-on; self-calibrating thresholds that need no per-instrument tuning; and a drastically simpler architecture — drift is a scalar time series in Delta, with no vector store anywhere in the core.

**What it costs.** Wasserstein needs representative bin values, so the bin schema must expose edge positions (it does). Multiple baseline rules per instrument multiply the number of comparisons — bounded and cheap, since each comparison is O(bins) over sparse histograms.

**Circular channels.** For a circular channel (wind bearing, per ADR-001) the linear Wasserstein is wrong at the 0°/360° wraparound; the circular (periodic) earth-mover's distance is required. The decision accommodates this, but the circular implementation is **deferred with the rest of the circular-statistics work** until the first circular channel is built.

**Designed-for, not built (over-engineering fence).**
- **Mahalanobis distance on the moment vector as an interpretable second opinion.** Wasserstein says *how much* a distribution drifted; it does not say *which* moment moved (variance blew up vs. it went skewed). A Mahalanobis distance of the standardized moment vector against the instrument's own history would add that interpretability and is self-calibrating by construction. It is **not built in the slice** — Wasserstein-from-bins carries the headline capability alone. It is promoted only if a real interpretability gap appears. If built, it needs a shrinkage covariance estimate (Ledoit–Wolf) or a trimmed moment vector, because the percentile collinearity that sank the cosine idea also makes the raw covariance near-singular.
- **PSI and JS** are kept available as documented siblings — useful as cross-checks and as the comparative material for the companion document's appendix, not as the primary signal.

**Companion document.** The ADR states the decision tersely; the companion document's appendix develops the full comparison — what Wasserstein, PSI, and JS each measure, the saturation and empty-bin failure modes, and the math — so the rationale is deep but kept out of the decision record.

**Coupling to other decisions.** Reads the histograms and fixed value axis of ADR-002, stays within one schema version per ADR-003, and compares as-of-consistent snapshots per ADR-004. The drift signal it produces is the primary input to whatever alerting/forecasting layers are fenced as designed-for elsewhere.

The analytical moments run as Spark-native aggregations (count, sum(value^k)) that distribute across partitions and combine across them — feasible because the power sums were chosen additive (ADR-006). This was validated by computing the moments both as a single-machine reference and as a distributed Spark aggregation over the same Delta table and confirming the fingerprints match to floating-point precision. The same additivity that gives bitemporal reproducibility (ADR-004) gives distribution for free; the binning counts distribute by the identical principle (implementation deferred — see below).

## Validation note (seasonality — confirming decision 3)

A simulation over a 90-day spring-to-summer span, scored with the vertical-slice notebook's **simplified** baseline — calibrate on the first 28 days and compare every later day against that fixed early-season reference — flagged 21 consecutive normal summer days as drift, their distances rising smoothly with the season, while *missing* a small injected fault that the inflated, season-contaminated threshold swamped. This is precisely the failure this ADR's Context anticipates and decision 3 is written to prevent: comparing a later season against an earlier-season baseline reads normal cyclic warming as drift.

The point of recording it is that **the fix is not new logic — it is the baseline already decided here.** A `same_hour_yesterday` or seasonal `historical_reference` baseline (decision 3) differences out the cycle, so normal seasonal warming lands near its seasonal reference and does not fire. The slice notebook implements only the simplest fixed baseline; that is a deliberate simplification of the *demonstration*, not the recommended policy, and running it across seasons reproduces the exact alarm-storm the seasonal baseline exists to avoid.

The vertical slice therefore validates injected faults on a short **in-season** window, where the fixed baseline is adequate and the injected fault is the only large distribution change; the seasonal baseline of decision 3 remains the specified mechanism for any multi-season deployment, and is **designed, not yet built** in the slice. This is an instance of a decision validated by *reproducing the failure it prevents* — the empirical detail (this run and the other injected-fault scenarios) is collected in the experiment log, `docs/experiments/simulation-results.md`.

---

*Authorship: architecture and all design decisions by the author. Implementation is AI-assisted — code generated against the documented architecture and decisions. This ADR records the reasoning; the code is the proof.*
