# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Process to Silver & Gold, then Detect Drift
# MAGIC
# MAGIC Reads bronze, derives the frozen bin schema, and **persists the medallion layers as Delta
# MAGIC tables** so the whole pipeline is browsable in the workspace:
# MAGIC
# MAGIC - **silver** `increment_fact` — signed per-bin **count deltas** per instrument-hour
# MAGIC - **gold** `histogram` — net bin counts per instrument-hour
# MAGIC - **gold** `fingerprints` — the 9-vector per instrument-hour (exact moments + percentiles + entropy)
# MAGIC
# MAGIC Then it runs the headline drift detection over daily windows and asserts the injected drift is
# MAGIC caught. Note the lineage: **moments come from power sums (exact, ADR-006), not from the
# MAGIC histogram**; percentiles and entropy come from the bins. So `fingerprints` is derived from the
# MAGIC readings + schema, while `histogram` is the binned view — two complementary gold artifacts.
# MAGIC
# MAGIC The bin assignment runs with the validated package logic on the driver (Option 1; the increment
# MAGIC fact is materialized for inspection and downstream reads without un-fencing distributed bin
# MAGIC assignment, which stays designed-for — ADR-010).
# MAGIC
# MAGIC **Run order:** run `01_ingest_bronze` first.

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

import numpy as np
import pandas as pd
from datetime import datetime

from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, DoubleType

from binmoments.binning import derive_bin_schema
from binmoments.stats import PowerSums, assemble_fingerprint
from binmoments.drift import DriftDetector

CATALOG, SCHEMA = "workspace", "binmoments"
BRONZE       = f"{CATALOG}.{SCHEMA}.bronze_readings"
FACT         = f"{CATALOG}.{SCHEMA}.increment_fact"     # silver
HIST         = f"{CATALOG}.{SCHEMA}.histogram"          # gold
FINGERPRINTS = f"{CATALOG}.{SCHEMA}.fingerprints"       # gold
INGEST_TIME  = "2024-07-08T00:00:00"                    # single batch arrival (transaction time)

# COMMAND ----------

# Read bronze to the driver (Option 1: validated Python on the driver; fine at slice scale).
pdf = (spark.table(BRONZE)
       .select("instrument_id", "event_time", "value")
       .orderBy("event_time").toPandas())
pdf["event_hour"] = pd.to_datetime(pdf["event_time"]).dt.strftime("%Y-%m-%dT%H")
pdf["day"] = pd.to_datetime(pdf["event_time"]).dt.date
instrument_id = pdf["instrument_id"].iloc[0]
print(f"{len(pdf)} readings, instrument {instrument_id}")

# COMMAND ----------

# Derive the frozen bin schema on the first 14 (clean) days.
days = sorted(pdf["day"].unique())
clean_days = days[:14]
clean_vals = pdf.loc[pdf["day"].isin(clean_days), "value"].tolist()
schema = derive_bin_schema(
    clean_vals, scope=f"instrument:{instrument_id}", channel="temperature", target_bin_count=48,
    fit_start=str(days[0]), fit_end=str(clean_days[-1]), created_at=str(days[0]),
)
print("frozen schema:", schema.schema_id)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Silver — the increment fact (per instrument-hour-bin count deltas)
# MAGIC One signed delta per non-empty (instrument, schema, event_hour, bin). A batch of readings
# MAGIC produces these count deltas; corrections would later append compensating deltas (ADR-004).

# COMMAND ----------

fact_rows = []
fp_rows = []
for hour, g in pdf.groupby("event_hour"):
    vals = g["value"].tolist()
    counts = schema.bin_counts(vals)                       # per-bin counts (validated API)
    for b, c in enumerate(counts):
        if c:
            fact_rows.append((instrument_id, schema.schema_id, hour, int(b), float(c), INGEST_TIME))
    # fingerprint for this hour: moments from exact power sums, shape from bins
    ps = PowerSums.from_values(vals)
    fp = assemble_fingerprint(ps, counts, schema).vector()
    fp_rows.append((instrument_id, hour, schema.schema_id, *[float(x) for x in fp]))

fact_schema = StructType([
    StructField("instrument_id", StringType()), StructField("bin_schema_id", StringType()),
    StructField("event_hour", StringType()),    StructField("bin_index", IntegerType()),
    StructField("count_delta", DoubleType()),   StructField("arrival_time", StringType()),
])
# overwrite for a re-runnable demo; a production fact appends (it is append-only, ADR-004).
spark.createDataFrame(fact_rows, fact_schema) \
     .write.format("delta").mode("overwrite").saveAsTable(FACT)
print(f"silver  {FACT}: {spark.table(FACT).count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Gold — histogram (net bin counts) and fingerprints (the 9-vector)

# COMMAND ----------

# Gold histogram = the increment fact aggregated to net counts (the served distribution).
(spark.table(FACT)
   .groupBy("instrument_id", "bin_schema_id", "event_hour", "bin_index")
   .agg(F.sum("count_delta").alias("count"))
   .filter("count != 0")
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

# COMMAND ----------

# MAGIC %md
# MAGIC ### Scaling check — distributed moments match the single-machine reference
# MAGIC The power sums computed as a Spark aggregation equal the validated reference exactly (ADR-010).

# COMMAND ----------

agg = (spark.table(BRONZE).groupBy("instrument_id").agg(
    F.count("value").alias("n"), F.sum("value").alias("s1"),
    F.sum(F.col("value") ** 2).alias("s2"), F.sum(F.col("value") ** 3).alias("s3"),
    F.sum(F.col("value") ** 4).alias("s4")).first())
ps_spark = PowerSums(n=agg["n"], s1=agg["s1"], s2=agg["s2"], s3=agg["s3"], s4=agg["s4"])
ps_ref = PowerSums.from_values(pdf["value"].tolist())
match = all(abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b)) for a, b in [
    (ps_ref.mean, ps_spark.mean), (ps_ref.variance, ps_spark.variance),
    (ps_ref.skewness, ps_spark.skewness), (ps_ref.kurtosis_excess, ps_spark.kurtosis_excess)])
print("distributed moments match reference:", match)
assert match, "distributed and reference moments disagree"

# COMMAND ----------

# MAGIC %md
# MAGIC ### Headline — drift detection over daily windows (the detector sees only the readings)

# COMMAND ----------

# Daily distributions straight from the readings (matches the validated run exactly).
by_day = {d: g["value"].tolist() for d, g in pdf.groupby("day")}
daily = {d: schema.bin_counts(by_day[d]) for d in sorted(by_day)}
days_sorted = sorted(daily)
clean = days_sorted[:14]

detector = DriftDetector.calibrate(schema, [daily[d] for d in clean], k=8.0)
print(f"self-calibrated threshold: {detector.threshold:.3f} degC\n")

drift_start, drift_end = datetime(2024, 6, 27).date(), datetime(2024, 6, 30).date()
print("date         distance  verdict       injected?")
print("-----------  --------  -----------   ---------")
caught = false_alarms = 0
for d in days_sorted[14:]:
    dist = detector.distance(daily[d])
    flagged = dist > detector.threshold
    truth = drift_start <= d < drift_end
    caught += int(flagged and truth)
    false_alarms += int(flagged and not truth)
    print(f"{d}  {dist:7.3f}  {'** DRIFT **' if flagged else 'normal     '}   {'yes' if truth else ''}")
print(f"\ninjected drift days caught: {caught}/3     false alarms: {false_alarms}")
assert caught == 3 and false_alarms == 0, "VALIDATION FAILED — detector did not match ground truth"
print("VALIDATED on Databricks: every injected drift day caught, zero false alarms.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Schema table + plottable view
# MAGIC Persist the bin **edges** (so a histogram is self-describing and plottable), and create a
# MAGIC view that returns, per (instrument, event_hour), every bin with its edges and a **zero-filled**
# MAGIC count -- ready to plot.

# COMMAND ----------

from binmoments.serving import schema_edge_rows

SCHEMA_TBL = f"{CATALOG}.{SCHEMA}.bin_schema"
PLOT_VIEW  = f"{CATALOG}.{SCHEMA}.histogram_plot"

edge_rows = [(schema.schema_id, b, lo, hi, mid) for (b, lo, hi, mid) in schema_edge_rows(schema)]
schema_tbl_schema = StructType([
    StructField("bin_schema_id", StringType()), StructField("bin_index", IntegerType()),
    StructField("lower_edge", DoubleType()), StructField("upper_edge", DoubleType()),
    StructField("midpoint", DoubleType()),
])
spark.createDataFrame(edge_rows, schema_tbl_schema) \
     .write.format("delta").mode("overwrite").saveAsTable(SCHEMA_TBL)
print(f"schema  {SCHEMA_TBL}: {spark.table(SCHEMA_TBL).count()} bins")

# Plottable view: every bin (with edges) for every (instrument, hour), empty bins as 0.
spark.sql(f"""
    CREATE OR REPLACE VIEW {PLOT_VIEW} AS
    WITH hours AS (
        SELECT DISTINCT instrument_id, bin_schema_id, event_hour FROM {HIST}
    ),
    grid AS (
        SELECT h.instrument_id, h.event_hour, s.bin_schema_id, s.bin_index,
               s.lower_edge, s.upper_edge, s.midpoint
        FROM hours h JOIN {SCHEMA_TBL} s ON h.bin_schema_id = s.bin_schema_id
    )
    SELECT g.instrument_id, g.event_hour, g.bin_index,
           g.lower_edge, g.upper_edge, g.midpoint,
           COALESCE(x.count, 0.0) AS count
    FROM grid g
    LEFT JOIN {HIST} x
      ON  g.instrument_id = x.instrument_id
      AND g.bin_schema_id = x.bin_schema_id
      AND g.event_hour    = x.event_hour
      AND g.bin_index     = x.bin_index
""")
print(f"view    {PLOT_VIEW} created (edges + zero-filled counts, ready to plot)")

# COMMAND ----------

# MAGIC %md
# MAGIC ### The medallion, now browsable

# COMMAND ----------

for t in [BRONZE, FACT, HIST, FINGERPRINTS, SCHEMA_TBL]:
    print(f"{t}: {spark.table(t).count()} rows")
print(f"{PLOT_VIEW}: view (per-hour histogram with edges, zero-filled)")

print("\nsample of gold fingerprints (watch the mean rise on the injected drift days):")
(spark.table(FINGERPRINTS)
   .select("event_hour", "mean", "variance", "p95", "entropy_norm")
   .orderBy("event_hour").show(6, truncate=False))
