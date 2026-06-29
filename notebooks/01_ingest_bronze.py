# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Ingest to Bronze (scenario switcher)
# MAGIC
# MAGIC Simulates a temperature stream for one instrument and lands the raw readings in
# MAGIC `bronze_readings`. The injected fault(s) are also written to a separate `ground_truth` table,
# MAGIC used only for **scoring** in notebook 02 (never by the detector's computation), so switching
# MAGIC scenarios flows through 02 and 04 automatically.
# MAGIC
# MAGIC **To switch scenarios, change the single `SCENARIO = "..."` line below.** Each scenario carries
# MAGIC its own simulation window, so the fault and the right window always travel together.
# MAGIC
# MAGIC **Workflow:** run `05` to reset, then `01 → 02 → 03 → 04` to see how the active scenario goes.

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

import json
from datetime import datetime, timedelta

from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, DoubleType

from binmoments.simulator import Simulator, DriftWindow, FaultKind

CATALOG, SCHEMA = "workspace", "binmoments"
BRONZE       = f"{CATALOG}.{SCHEMA}.bronze_readings"
GROUND_TRUTH = f"{CATALOG}.{SCHEMA}.ground_truth"

# COMMAND ----------

# MAGIC %md
# MAGIC ### Choose a scenario
# MAGIC Set `SCENARIO` to one of: `A`, `B`, `C`, `D`, `E`, `S`. Exactly one is active; the notebook
# MAGIC prints which one ran. Notebook 02 calibrates on the first 28 clean days, so in-season faults
# MAGIC are placed after that.

# COMMAND ----------

SCENARIO = "A"   # <-- change this one line to switch scenarios

# A short in-season window (late June, 28 days). Seasonal trend is negligible here, so a fixed
# baseline is adequate and the injected fault is the only large distribution change.
IN_SEASON_START = datetime(2024, 6, 10)
IN_SEASON_DAYS  = 28

# Each scenario = (description, start, n_days, drift_windows). The window travels with the fault.
SCENARIOS = {
    # A — one clean mean shift, +3 degC over 3 days. The canonical pass.
    "A": (
        "mean shift +3 degC, 3 days (in-season)",
        IN_SEASON_START, IN_SEASON_DAYS,
        [DriftWindow(datetime(2024, 6, 27), datetime(2024, 6, 30), FaultKind.MEAN_SHIFT, 3.0)],
    ),
    # B — a BIGGER mean shift, +8 degC. Watch the drift DISTANCE in 02 track the magnitude
    #     (Wasserstein of a pure shift = the shift; see the math companion).
    "B": (
        "mean shift +8 degC, 3 days (in-season)",
        IN_SEASON_START, IN_SEASON_DAYS,
        [DriftWindow(datetime(2024, 6, 27), datetime(2024, 6, 30), FaultKind.MEAN_SHIFT, 8.0)],
    ),
    # C — TWO faults, different sizes and times. 02 should catch both, quiet elsewhere.
    "C": (
        "two mean shifts: +3 degC (Jun 20-21) and +6 degC (Jun 27-29), in-season",
        IN_SEASON_START, IN_SEASON_DAYS,
        [
            DriftWindow(datetime(2024, 6, 20), datetime(2024, 6, 22), FaultKind.MEAN_SHIFT, 3.0),
            DriftWindow(datetime(2024, 6, 27), datetime(2024, 6, 30), FaultKind.MEAN_SHIFT, 6.0),
        ],
    ),
    # D — VARIANCE INFLATION x3: spread triples, MEAN UNCHANGED. The illuminating case — a
    #     mean-threshold monitor sees nothing; the distribution widens (plot it in 04). The
    #     Wasserstein signal is quieter here, the detector's known soft spot (ADR-005).
    "D": (
        "variance inflation x3, 3 days (in-season) — mean unchanged",
        IN_SEASON_START, IN_SEASON_DAYS,
        [DriftWindow(datetime(2024, 6, 27), datetime(2024, 6, 30), FaultKind.VARIANCE_INFLATION, 3.0)],
    ),
    # E — a SUBTLE shift, +1 degC, likely BELOW the self-calibrated threshold. Finds the
    #     detection floor: 02 may report these days as normal (low recall by design).
    "E": (
        "mean shift +1 degC, 3 days (in-season) — near/below threshold",
        IN_SEASON_START, IN_SEASON_DAYS,
        [DriftWindow(datetime(2024, 6, 27), datetime(2024, 6, 30), FaultKind.MEAN_SHIFT, 1.0)],
    ),
    # S — SEASONALITY confound: a +3 degC fault on a LONG 90-day spring-to-summer window. The fixed
    #     baseline reads normal seasonal warming as drift (many false alarms) and the small fault is
    #     swamped. This reproduces the failure ADR-005 decision 3 (seasonal baseline) prevents.
    "S": (
        "mean shift +3 degC on a 90-day spring->summer window (reproduces the seasonality confound)",
        datetime(2024, 4, 1), 90,
        [DriftWindow(datetime(2024, 6, 1), datetime(2024, 6, 4), FaultKind.MEAN_SHIFT, 3.0)],
    ),
}

description, START, N_DAYS, drift_windows = SCENARIOS[SCENARIO]
END = START + timedelta(days=N_DAYS)
SAMPLES = 60   # readings/hour. For a much longer window, drop to ~12 to keep the run light.

print(f"SCENARIO {SCENARIO}: {description}")
print(f"window: {START.date()} .. {END.date()}  ({N_DAYS} days, {SAMPLES}/hour)")

# COMMAND ----------

sim = Simulator(
    instrument_id="TEMP-001",
    start=START, end=END,
    sampling_per_hour=SAMPLES, seed=11,
    drift_windows=drift_windows,
)
records, ground_truth = sim.run()

print(f"simulated {len(records)} readings")
print("injected ground-truth fault(s):")
for e in ground_truth:
    print(f"  {e.kind}  {e.start} -> {e.end}  {e.detail}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Write the readings to bronze, and the ground truth to its own table

# COMMAND ----------

rows = [
    {
        "instrument_id":  r["instrument_id"],
        "measurement_id": r["measurement_id"],
        "event_time":     r["event_time"],
        "arrival_time":   r["arrival_time"],
        "channel":        "temperature",
        "value":          float(r["values"]["temperature"]),
    }
    for r in records
]
bronze_schema = StructType([
    StructField("instrument_id", StringType()), StructField("measurement_id", StringType()),
    StructField("event_time", StringType()),    StructField("arrival_time", StringType()),
    StructField("channel", StringType()),        StructField("value", DoubleType()),
])
(spark.createDataFrame(rows, bronze_schema)
   .withColumn("event_time",   F.to_timestamp("event_time",   "yyyy-MM-dd'T'HH:mm:ss"))
   .withColumn("arrival_time", F.to_timestamp("arrival_time", "yyyy-MM-dd'T'HH:mm:ss"))
   .write.format("delta").mode("overwrite").saveAsTable(BRONZE))
print(f"wrote {spark.table(BRONZE).count()} rows to {BRONZE}")

# Ground truth -> its own table. Read only for SCORING (notebooks 02, 04); never by the detector.
gt_rows = [(d["kind"], d["start"], d["end"], json.dumps(d["detail"]))
           for d in (e.to_dict() for e in ground_truth)]
gt_schema = StructType([
    StructField("kind", StringType()), StructField("start", StringType()),
    StructField("end", StringType()),  StructField("detail", StringType()),
])
spark.createDataFrame(gt_rows, gt_schema) \
     .write.format("delta").mode("overwrite").saveAsTable(GROUND_TRUTH)
print(f"wrote {spark.table(GROUND_TRUTH).count()} ground-truth fault(s) to {GROUND_TRUTH}")

spark.table(BRONZE).orderBy("event_time").show(5, truncate=False)
