# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Ingest to Bronze (scenario switcher)
# MAGIC
# MAGIC Simulates a long temperature stream for one instrument and lands the raw readings in
# MAGIC `bronze_readings`. A fault is injected per the **active scenario** below — uncomment exactly
# MAGIC one. The injected fault(s) are also written to a separate `ground_truth` table, used only for
# MAGIC **scoring** in notebook 02 (never by the detector's computation), so switching scenarios flows
# MAGIC through 02 and 04 automatically.
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

START   = datetime(2024, 4, 1)
N_DAYS  = 90                         # 90-day interval. For a full year use 365 and drop
SAMPLES = 60                         # SAMPLES to ~12/hour to keep the run light.
END     = START + timedelta(days=N_DAYS)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Drift scenario — uncomment exactly ONE block
# MAGIC Notebook 02 calibrates on the first 28 **clean** days, so every fault below is placed well
# MAGIC after that (May onward). Re-run 05 then 01→04 after switching.

# COMMAND ----------

# --- Scenario A (DEFAULT): one clean mean shift, +3 degC over 3 days -----------------------------
drift_windows = [
    DriftWindow(datetime(2024, 6, 1), datetime(2024, 6, 4), FaultKind.MEAN_SHIFT, 3.0),
]

# --- Scenario B: a BIGGER mean shift, +8 degC. Watch the drift DISTANCE in 02 track the magnitude
#     (Wasserstein of a pure shift = the shift; see the math companion). ---------------------------
# drift_windows = [
#     DriftWindow(datetime(2024, 6, 1), datetime(2024, 6, 4), FaultKind.MEAN_SHIFT, 8.0),
# ]

# --- Scenario C: TWO faults, different sizes and times. 02 should catch both, quiet elsewhere. ---
# drift_windows = [
#     DriftWindow(datetime(2024, 5, 10), datetime(2024, 5, 12), FaultKind.MEAN_SHIFT, 3.0),
#     DriftWindow(datetime(2024, 6, 1),  datetime(2024, 6, 4),  FaultKind.MEAN_SHIFT, 6.0),
# ]

# --- Scenario D: VARIANCE INFLATION x3 — spread triples, MEAN UNCHANGED. The illuminating case:
#     a mean-threshold monitor sees nothing; the distribution clearly widens (plot it in 04).
#     The Wasserstein signal is quieter here — the detector's known soft spot (ADR-005). ----------
# drift_windows = [
#     DriftWindow(datetime(2024, 6, 1), datetime(2024, 6, 4), FaultKind.VARIANCE_INFLATION, 3.0),
# ]

# --- Scenario E: a SUBTLE shift, +1 degC — likely BELOW the self-calibrated threshold.
#     Finds the detection floor: 02 may report these days as normal (low recall by design). -------
# drift_windows = [
#     DriftWindow(datetime(2024, 6, 1), datetime(2024, 6, 4), FaultKind.MEAN_SHIFT, 1.0),
# ]

# COMMAND ----------

sim = Simulator(
    instrument_id="TEMP-001",
    start=START, end=END,
    sampling_per_hour=SAMPLES, seed=11,
    drift_windows=drift_windows,
)
records, ground_truth = sim.run()

print(f"simulated {len(records)} readings over {N_DAYS} days ({START.date()} .. {END.date()})")
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
