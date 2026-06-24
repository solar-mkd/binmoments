# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Ingest to Bronze
# MAGIC
# MAGIC Simulate a 28-day temperature stream for one instrument, with a **known** mean-shift drift
# MAGIC injected on 27–29 June (the ground-truth anomaly), and land the raw readings in the bronze
# MAGIC Delta table `workspace.binmoments.bronze_readings`.
# MAGIC
# MAGIC The drift is injected into the *readings only*; nothing in the stored data marks which days
# MAGIC are faulty. Notebook 02 must rediscover them blind.
# MAGIC
# MAGIC **Run order:** run this before `02_fingerprint_and_drift`.

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

from datetime import datetime, timedelta

from binmoments.simulator import Simulator, DriftWindow, FaultKind

CATALOG, SCHEMA = "workspace", "binmoments"
TABLE = f"{CATALOG}.{SCHEMA}.bronze_readings"

start = datetime(2024, 6, 10)
drift_start, drift_end = datetime(2024, 6, 27), datetime(2024, 6, 30)  # known +4C drift (3 days)

sim = Simulator(
    instrument_id="TEMP-001",
    start=start,
    end=start + timedelta(days=28),
    sampling_per_hour=60,
    seed=11,
    drift_windows=[DriftWindow(drift_start, drift_end, FaultKind.MEAN_SHIFT, 4.0)],
)
records, ground_truth = sim.run()

print(f"simulated {len(records)} readings")
print("injected ground-truth faults:")
for e in ground_truth:
    print(f"  {e.kind}  {e.start} -> {e.end}  {e.detail}")

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, DoubleType

# Flatten the simulator's records into one row per reading (long format: one channel per row).
rows = [
    {
        "instrument_id":  r["instrument_id"],
        "measurement_id": r["measurement_id"],
        "event_time":     r["event_time"],     # ISO strings; parsed to timestamps below
        "arrival_time":   r["arrival_time"],
        "channel":        "temperature",
        "value":          float(r["values"]["temperature"]),
    }
    for r in records
]

spark_schema = StructType([
    StructField("instrument_id",  StringType()),
    StructField("measurement_id", StringType()),
    StructField("event_time",     StringType()),
    StructField("arrival_time",   StringType()),
    StructField("channel",        StringType()),
    StructField("value",          DoubleType()),
])

df = (
    spark.createDataFrame(rows, spark_schema)
    .withColumn("event_time",   F.to_timestamp("event_time",   "yyyy-MM-dd'T'HH:mm:ss"))
    .withColumn("arrival_time", F.to_timestamp("arrival_time", "yyyy-MM-dd'T'HH:mm:ss"))
)

# overwrite makes this notebook safely re-runnable. A production bronze layer would append
# (it is append-only, ADR-004/009); overwrite is the convenience choice for a re-runnable demo.
df.write.format("delta").mode("overwrite").saveAsTable(TABLE)

print(f"wrote {df.count()} rows to {TABLE}")
df.orderBy("event_time").show(5, truncate=False)
