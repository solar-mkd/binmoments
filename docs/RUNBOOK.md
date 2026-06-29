# Running & Verifying BinMoments

This guide lets anyone reproduce the project's central claim — *the system catches injected
anomalies it was never told about* — in two ways: a one-minute local check, and a full run on
Databricks. Both use the same code and the same ground-truth simulator.

---

## What you are verifying

The simulator generates realistic sensor data and **injects a known fault** into the readings, while
keeping a separate ground-truth log. The detector then runs on the readings **alone** and must
rediscover the fault — flagging the right window and staying quiet everywhere else. Because the
truth is known and hidden from the detector, "it works" is a measured result, not a claim.

---

## Option A — Verify locally in one minute (no Databricks needed)

The fastest proof. Requires Python 3.10+.

```bash
git clone https://github.com/solar-mkd/binmoments.git
cd binmoments
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .
pip install pytest
pytest -q
```

You should see the full suite pass (60+ tests). Among them: the end-to-end drift test injects a
known mean-shift, runs the detector blind, and asserts it caught every injected day with zero false
alarms; the moments tests pin the power-sum exactness (including a guard against the reversed
bin-midpoint method); the bitemporal-fact tests pin as-of reproducibility under corrections; and the
serving tests prove the current-state read model equals a full rebuild from the fact. Browse the
`tests/` folder to see each scenario.

---

## Option B — Run on Databricks Free Edition (proves it runs on the platform)

This reproduces the analytical pipeline on real Delta tables and serverless compute.

### 1. Get a workspace
Sign up for **Databricks Free Edition** (free, serverless, no cluster to manage):
<https://www.databricks.com/learn/free-edition>. Confirm the **"Free Edition"** badge appears
next to the Databricks logo (top-left).

### 2. Bring in the code as a Git folder
- Top-right user menu -> **Settings -> Linked accounts -> Add Git credential**, link your GitHub
  account (OAuth, or a personal access token for a private fork).
- Left sidebar -> **Workspace -> (your home) -> Create -> Git folder**, paste the repo URL, and
  create it. The repo clones into your workspace as a folder named `binmoments`.

### 3. Create the schema (one time)
Open the **SQL Editor** (or a notebook) and run:

```sql
CREATE SCHEMA IF NOT EXISTS workspace.binmoments;
```

### 4. Run the notebooks
Inside the Git folder, open `notebooks/` and run, **in order**, connecting each to **Serverless**
(top-right) and choosing **Run all**:

1. **`05_reset`** — drops any existing tables/views for a clean slate (everything is regenerable).
2. **`01_ingest_bronze`** — simulates the stream for the active scenario and writes
   `bronze_readings` plus a separate `ground_truth` table. Switch scenarios by changing the single
   `SCENARIO = "A"` line (see below); the default `A` is the canonical clean detection.
3. **`02_fingerprint_and_drift`** — builds the medallion (silver `increment_fact`; gold `histogram`,
   `fingerprints`, `bin_schema`; view `histogram_plot`), runs the distributed moments, and scores
   drift against the `ground_truth` table — so it adapts to whichever scenario is active.
4. **`03_materialize_current_state`** — maintains the current-state read model by `MERGE` and asserts
   it equals a full rebuild from the fact.
5. **`04_plot_histogram`** — plots the histograms, including a clean-vs-drift overlay that auto-picks
   its hours from the ground truth, so the fault is visible (a shift, or a widening for variance).

`00_setup` is run automatically by the others (via `%run`); you do not run it directly.

### 5. What success looks like
The drift cell of `02` prints a per-day table and a summary:

```
injected days caught: 3/3  (recall 100%)     false alarms: 0
```

By default `02` runs in reporting mode (it prints the verdict). Set `STRICT = True` at the top of
`02` for the canonical mean-shift scenario to additionally **assert** the result — the run then
errors rather than passing quietly if detection ever fails to match the ground truth. Notebook `03`
asserts its current-state consistency unconditionally.

---

## Explore the detector's whole range (the scenario switcher)

`01_ingest_bronze` has a `SCENARIO` selector. Change the one line `SCENARIO = "A"` to any of:

- **A** — mean shift +3 degC → clean detection (3/3, no false alarms).
- **B** — mean shift +8 degC → the drift *distance* scales up with the magnitude.
- **C** — two faults of different size → both caught and ranked by severity.
- **D** — variance ×3, mean unchanged → the **soft spot**: a mean-monitor sees nothing, and the
  daily Wasserstein stays quiet (the change is in the fingerprint's variance component; the
  variance-moment and Mahalanobis signals that would flag it are designed-for, ADR-005).
- **E** — mean shift +1 degC → below the self-calibrated threshold: the **detection floor**, correctly not chased.
- **S** — +3 degC on a 90-day spring→summer window → the **seasonality confound**: a fixed baseline
  reads normal seasonal warming as drift, reproducing the failure the seasonal baseline (ADR-005)
  prevents.

After switching, re-run `05 → 01 → 02` (and `03`, `04`). The scoring follows the `ground_truth`
table automatically — there is nothing to edit in `02`. Every one of these runs is recorded and
explained in **[`docs/experiments/simulation-results.md`](experiments/simulation-results.md)**.

---

## How to convince yourself it is not rigged

- The detector is calibrated **only** on the leading clean days and never sees which later days are
  faulty — the injected window is not in the stored readings, only in the separate `ground_truth`
  table, which the detector's computation never reads (it is used only for scoring afterward).
- Switch scenarios (above) and watch the verdict change: bigger faults give bigger distances (B),
  multiple faults are each caught and ranked (C), a sub-threshold shift is correctly ignored (E),
  and a fixed baseline across seasons fails exactly as the design predicts (S).
- Set a scenario's magnitude to a tiny value and confirm the detector raises **no** alarms — the
  other half of correctness: not crying wolf.

---

## Notes

- Free Edition is serverless and ephemeral: the notebooks set up their environment on each run, so
  there is nothing to install or keep warm.
- Local edits are the source of truth: edit in your IDE, push to GitHub, and **Pull** the Git
  folder in Databricks to refresh the workspace copy.
