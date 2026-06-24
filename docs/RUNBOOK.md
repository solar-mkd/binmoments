# Running & Verifying BinMoments

This guide lets anyone reproduce the project's central claim — *the system catches injected
anomalies it was never told about* — in two ways: a one-minute local check, and a full run on
Databricks. Both use the same code and the same ground-truth simulator.

---

## What you are verifying

The simulator generates realistic sensor data and **injects a known fault** (a temperature drift)
into the readings, while keeping a separate ground-truth log. The detector then runs on the
readings **alone** and must rediscover the fault — flagging the right window and staying quiet
everywhere else. Because the truth is known and hidden from the detector, "it works" is a measured
result, not a claim.

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

You should see the full suite pass (50+ tests). The ones that prove the headline are in
`tests/test_drift.py` — in particular `test_end_to_end_mean_shift_caught_with_no_false_alarms`,
which injects a known drift, runs the detector blind, and asserts it caught every injected day with
zero false alarms. The moments-reversal and bitemporal guarantees are likewise pinned by tests in
`tests/test_moments.py` and `tests/test_fact.py`.

To watch the detection happen with a readable readout rather than a pass/fail:

```bash
python -c "from tests.test_drift import *"   # or open tests/test_drift.py to see the scenario
```

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
Inside the Git folder, open `notebooks/` and run, **in order**:

1. **`01_ingest_bronze`** — connect to **Serverless** (top-right), then **Run all**. It simulates
   28 days with a hidden drift on 27-29 June and writes `workspace.binmoments.bronze_readings`.
2. **`02_fingerprint_and_drift`** — **Run all**. It reads the bronze table, computes the
   distributed moments, calibrates the detector on the clean reference days, and scores the rest.

`00_setup` is run automatically by the other two (via `%run`); you do not run it directly.

### 5. What success looks like
The final cell of `02` prints a per-day table and ends with:

```
injected drift days caught: 3/3     false alarms: 0
VALIDATED on Databricks: every injected drift day caught, zero false alarms.
```

The notebook **asserts** this, so if the detector ever failed to match the ground truth, the run
would error rather than pass quietly.

---

## How to convince yourself it is not rigged

- The detector is calibrated **only** on the first 14 days and never sees which later days are
  faulty — the injected window is not present in the stored data, only in the simulator's separate
  ground-truth log.
- Change the scenario in `01_ingest_bronze` — move the drift window, change its size, or add a
  second one — re-run both notebooks, and watch the detector track the change. (You will also need
  to update the expected window in `02` to match your edit.)
- Set the drift magnitude to `0.0` (no real fault) and confirm the detector raises **no** alarms —
  the other half of correctness: not crying wolf.

---

## Notes

- Free Edition is serverless and ephemeral: the notebooks set up their environment on each run, so
  there is nothing to install or keep warm.
- Local edits are the source of truth: edit in your IDE, push to GitHub, and **Pull** the Git
  folder in Databricks to refresh the workspace copy.
