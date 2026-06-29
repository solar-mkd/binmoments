# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Process to Silver & Gold, then Detect Drift (scenario-aware)
# MAGIC
# MAGIC Persists the medallion (silver `increment_fact`; gold `histogram`, `fingerprints`, `bin_schema`;
# MAGIC view `histogram_plot`) and runs drift detection. It scores against the `ground_truth` table that
# MAGIC `01` wrote, so it adapts to whatever scenario is active — no hardcoded drift dates.
# MAGIC
# MAGIC Moments come from power sums (exact, ADR-006), not the histogram; percentiles/entropy from bins.
# MAGIC Bin assignment runs with validated package logic on the driver (Option A; ADR-010).
# MAGIC
# MAGIC **Run order:** `05` (reset) → `01` → `02`.

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

import numpy as np
import pandas as pd
from datetime import timedelta

from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, DoubleType

from binmoments.binning import derive_bin_schema
from binmoments.stats import PowerSums, assemble_fingerprint
from binmoments.drift import DriftDetector
from binmoments.serving import schema_edge_rows

CATALOG, SCHEMA = "workspace", "binmoments"
BRONZE       = f"{CATALOG}.{SCHEMA}.bronze_readings"
GROUND_TRUTH = f"{CATALOG}.{SCHEMA}.ground_truth"
FACT         = f"{CATALOG}.{SCHEMA}.increment_fact"     # silver
HIST         = f"{CATALOG}.{SCHEMA}.histogram"          # gold
FINGERPRINTS = f"{CATALOG}.{SCHEMA}.fingerprints"       # gold
SCHEMA_TBL   = f"{CATALOG}.{SCHEMA}.bin_schema"
PLOT_VIEW    = f"{CATALOG}.{SCHEMA}.histogram_plot"
INGEST_TIME  = "2024-07-08T00:00:00"

CALIB_DAYS = 28        # number of leading CLEAN days used to calibrate the detector
STRICT     = False     # True -> assert 100% recall & zero false alarms (the canonical mean-shift case)

# COMMAND ----------

# Read bronze to the driver (Option A; validated Python logic).
pdf = (spark.table(BRONZE)
       .select("instrument_id", "event_time", "value")
       .orderBy("event_time").toPandas())
pdf["event_hour"] = pd.to_datetime(pdf["event_time"]).dt.strftime("%Y-%m-%dT%H")
pdf["day"] = pd.to_datetime(pdf["event_time"]).dt.date
instrument_id = pdf["instrument_id"].iloc[0]
print(f"{len(pdf)} readings, instrument {instrument_id}, "
      f"{pdf['day'].min()} .. {pdf['day'].max()}")

# Injected days from the ground-truth table (used only for scoring).
gt = spark.table(GROUND_TRUTH).toPandas()
injected_days = set()
for _, r in gt.iterrows():
    s = pd.to_datetime(r["start"]).date()
    e = pd.to_datetime(r["end"]).date()
    d = s
    while d < e:
        injected_days.add(d)
        d += timedelta(days=1)
print(f"ground truth: {len(gt)} fault(s), {len(injected_days)} injected day(s): "
      f"{sorted(injected_days)}")

# COMMAND ----------

# Frozen bin schema, derived on the first CALIB_DAYS clean days.
all_days = sorted(pdf["day"].unique())
clean_days = [d for d in all_days if d not in injected_days][:CALIB_DAYS]
clean_vals = pdf.loc[pdf["day"].isin(clean_days), "value"].tolist()
schema = derive_bin_schema(
    clean_vals, scope=f"instrument:{instrument_id}", channel="temperature", target_bin_count=48,
    fit_start=str(clean_days[0]), fit_end=str(clean_days[-1]), created_at=str(clean_days[0]),
)
print("frozen schema:", schema.schema_id)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Silver — increment fact (per instrument-hour-bin count deltas)

# COMMAND ----------

fact_rows, fp_rows = [], []
for hour, g in pdf.groupby("event_hour"):
    vals = g["value"].tolist()
    counts = schema.bin_counts(vals)
    for b, c in enumerate(counts):
        if c:
            fact_rows.append((instrument_id, schema.schema_id, hour, int(b), float(c), INGEST_TIME))
    fp = assemble_fingerprint(PowerSums.from_values(vals), counts, schema).vector()
    fp_rows.append((instrument_id, hour, schema.schema_id, *[float(x) for x in fp]))

fact_schema = StructType([
    StructField("instrument_id", StringType()), StructField("bin_schema_id", StringType()),
    StructField("event_hour", StringType()),    StructField("bin_index", IntegerType()),
    StructField("count_delta", DoubleType()),   StructField("arrival_time", StringType()),
])
spark.createDataFrame(fact_rows, fact_schema) \
     .write.format("delta").mode("overwrite").saveAsTable(FACT)
print(f"silver  {FACT}: {spark.table(FACT).count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Gold — histogram, fingerprints, bin_schema; and the plottable view

# COMMAND ----------

(spark.table(FACT)
   .groupBy("instrument_id", "bin_schema_id", "event_hour", "bin_index")
   .agg(F.sum("count_delta").alias("count")).filter("count != 0")
   .write.format("delta").mode("overwrite").saveAsTable(HIST))
print(f"gold    {HIST}: {spark.table(HIST).count()} rows")

fp_schema = StructType([
    StructField("instrument_id", StringType()), StructField("event_hour", StringType()),
    StructField("bin_schema_id", StringType()),
    StructField("mean", DoubleType()),     StructField("variance", DoubleType()),
    StructField("skewness", DoubleType()), StructField("kurtosis_excess", DoubleType()),
    StructField("p50", DoubleType()), StructField("p90", DoubleType()),
    StructField("p95", DoubleType()), StructField("p99", DoubleType()),
    StructField("entropy_norm", DoubleType()),
])
spark.createDataFrame(fp_rows, fp_schema) \
     .write.format("delta").mode("overwrite").saveAsTable(FINGERPRINTS)
print(f"gold    {FINGERPRINTS}: {spark.table(FINGERPRINTS).count()} rows")

edge_rows = [(schema.schema_id, b, lo, hi, mid) for (b, lo, hi, mid) in schema_edge_rows(schema)]
schema_tbl_schema = StructType([
    StructField("bin_schema_id", StringType()), StructField("bin_index", IntegerType()),
    StructField("lower_edge", DoubleType()), StructField("upper_edge", DoubleType()),
    StructField("midpoint", DoubleType()),
])
spark.createDataFrame(edge_rows, schema_tbl_schema) \
     .write.format("delta").mode("overwrite").saveAsTable(SCHEMA_TBL)
print(f"schema  {SCHEMA_TBL}: {spark.table(SCHEMA_TBL).count()} bins")

spark.sql(f"""
    CREATE OR REPLACE VIEW {PLOT_VIEW} AS
    WITH hours AS (SELECT DISTINCT instrument_id, bin_schema_id, event_hour FROM {HIST}),
    grid AS (
        SELECT h.instrument_id, h.event_hour, s.bin_schema_id, s.bin_index,
               s.lower_edge, s.upper_edge, s.midpoint
        FROM hours h JOIN {SCHEMA_TBL} s ON h.bin_schema_id = s.bin_schema_id)
    SELECT g.instrument_id, g.event_hour, g.bin_index, g.lower_edge, g.upper_edge, g.midpoint,
           COALESCE(x.count, 0.0) AS count
    FROM grid g LEFT JOIN {HIST} x
      ON g.instrument_id=x.instrument_id AND g.bin_schema_id=x.bin_schema_id
     AND g.event_hour=x.event_hour AND g.bin_index=x.bin_index
""")
print(f"view    {PLOT_VIEW} created")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Drift detection — scored against the ground-truth table

# COMMAND ----------

by_day = {d: g["value"].tolist() for d, g in pdf.groupby("day")}
daily = {d: schema.bin_counts(by_day[d]) for d in sorted(by_day)}

calib = [d for d in sorted(daily) if d not in injected_days][:CALIB_DAYS]
detector = DriftDetector.calibrate(schema, [daily[d] for d in calib], k=8.0)
print(f"calibrated on {len(calib)} clean days; threshold {detector.threshold:.3f} degC\n")

scored = [d for d in sorted(daily) if d not in set(calib)]
caught = false_alarms = injected_total = quiet_clean = 0
print("date         distance  verdict       injected?")
print("-----------  --------  -----------   ---------")
for d in scored:
    inj = d in injected_days
    injected_total += int(inj)
    dist = detector.distance(daily[d])
    flag = dist > detector.threshold
    caught += int(flag and inj)
    false_alarms += int(flag and not inj)
    if inj or flag:    # print only the interesting days
        print(f"{d}  {dist:7.3f}  {'** DRIFT **' if flag else 'normal     '}   {'yes' if inj else ''}")
    elif not flag and not inj:
        quiet_clean += 1
print(f"... and {quiet_clean} other scored days: all normal")

recall = (caught / injected_total) if injected_total else float("nan")
print(f"\ninjected days caught: {caught}/{injected_total}  (recall {recall:.0%})     "
      f"false alarms: {false_alarms}")
if STRICT:
    assert injected_total > 0 and caught == injected_total and false_alarms == 0, \
        "STRICT check failed (expected all injected days caught, zero false alarms)"
    print("STRICT: every injected day caught, zero false alarms.")
else:
    print("(reporting mode — set STRICT=True to assert the canonical mean-shift result)")

# COMMAND ----------

# MAGIC %md
# MAGIC ### The medallion, now browsable

# COMMAND ----------

for t in [BRONZE, GROUND_TRUTH, FACT, HIST, FINGERPRINTS, SCHEMA_TBL]:
    print(f"{t}: {spark.table(t).count()} rows")
print(f"{PLOT_VIEW}: view (per-hour histogram with edges, zero-filled)")
