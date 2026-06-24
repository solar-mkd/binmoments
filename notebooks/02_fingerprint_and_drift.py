# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Fingerprint & Drift (the headline, on-platform)
# MAGIC
# MAGIC Read the bronze readings, derive the frozen bin schema, and run self-calibrated Wasserstein
# MAGIC drift detection over daily distributions. **The detector sees only the readings** — the
# MAGIC injected drift (27–29 June) is hidden from it. We confirm it catches exactly those days with
# MAGIC zero false alarms, and the run ends with an assertion so the result is unambiguous.
# MAGIC
# MAGIC The moments use the **distributed** power-sum aggregation, shown alongside as the scale-out
# MAGIC path (validated to match the reference implementation; see ADR-010).
# MAGIC
# MAGIC **Run order:** run `01_ingest_bronze` first.

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

from collections import defaultdict
from datetime import datetime

from pyspark.sql import functions as F

from binmoments.binning import derive_bin_schema
from binmoments.drift import DriftDetector
from binmoments.stats import PowerSums

TABLE = "workspace.binmoments.bronze_readings"
bronze = spark.table(TABLE)
print("rows in bronze:", bronze.count())

# COMMAND ----------

# MAGIC %md
# MAGIC ### Distributed moments — the scale-out path
# MAGIC Power sums computed as Spark aggregations (`count`, `sum(value^k)`) distribute across
# MAGIC partitions and combine across them, because the sums are additive by design (ADR-006).

# COMMAND ----------

agg = (
    bronze.groupBy("instrument_id", "channel").agg(
        F.count("value").alias("n"),
        F.sum(F.col("value")).alias("s1"),
        F.sum(F.col("value") ** 2).alias("s2"),
        F.sum(F.col("value") ** 3).alias("s3"),
        F.sum(F.col("value") ** 4).alias("s4"),
    )
)
row = agg.first()
ps = PowerSums(n=row["n"], s1=row["s1"], s2=row["s2"], s3=row["s3"], s4=row["s4"])
print("overall moments (distributed):")
print(f"  mean={ps.mean:.4f}  variance={ps.variance:.4f}  "
      f"skewness={ps.skewness:.4f}  kurtosis_excess={ps.kurtosis_excess:.4f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Drift detection over daily distributions
# MAGIC Build a per-day distribution, fit the frozen schema on the first 14 (clean) days, calibrate
# MAGIC the detector to the instrument's own normal scatter, then score the remaining days.

# COMMAND ----------

# Pull (event_time, value) to build per-day histograms. Collect is fine at slice scale; the
# binning counts distribute by the same additive principle as the moments (ADR-010).
pdf = bronze.select("event_time", "value").orderBy("event_time").toPandas()

by_day = defaultdict(list)
for ts, val in zip(pdf["event_time"], pdf["value"]):
    by_day[ts.date()].append(float(val))
days = sorted(by_day)

clean_days = days[:14]
clean_vals = [v for d in clean_days for v in by_day[d]]
schema = derive_bin_schema(
    clean_vals, scope="instrument:TEMP-001", channel="temperature", target_bin_count=48,
    fit_start=str(days[0]), fit_end=str(clean_days[-1]), created_at=str(days[0]),
)
day_counts = {d: schema.bin_counts(by_day[d]) for d in days}

detector = DriftDetector.calibrate(schema, [day_counts[d] for d in clean_days], k=8.0)
print(f"schema {schema.schema_id}")
print(f"self-calibrated threshold: {detector.threshold:.3f} degC")

# COMMAND ----------

# Score every day after the reference window. The injected drift is 27-29 June; the detector
# does not know that — it only sees the distances.
drift_start, drift_end = datetime(2024, 6, 27).date(), datetime(2024, 6, 30).date()

print("date         distance  verdict       injected?")
print("-----------  --------  -----------   ---------")
caught = false_alarms = 0
for d in days[14:]:
    dist = detector.distance(day_counts[d])
    flagged = dist > detector.threshold
    truth = drift_start <= d < drift_end
    if flagged and truth:
        caught += 1
    if flagged and not truth:
        false_alarms += 1
    print(f"{d}  {dist:7.3f}  {'** DRIFT **' if flagged else 'normal     '}   {'yes' if truth else ''}")

print()
print(f"injected drift days caught: {caught}/3     false alarms: {false_alarms}")
assert caught == 3 and false_alarms == 0, "VALIDATION FAILED — detector did not match ground truth"
print("VALIDATED on Databricks: every injected drift day caught, zero false alarms.")
