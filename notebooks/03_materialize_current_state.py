# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Materialize the Current-State Histogram
# MAGIC
# MAGIC The increment fact is append-only (ADR-004): every reading and every correction is a signed
# MAGIC delta keyed by (instrument, schema, event_hour, bin). Reading the *current* histogram from it
# MAGIC means summing all deltas for each key — wasteful at millions of rows when you almost always
# MAGIC want "the latest state".
# MAGIC
# MAGIC This notebook maintains a materialized **current-state** table that collapses transaction time
# MAGIC (all known deltas applied, including late corrections — ADR-020 option A). It is a derived,
# MAGIC rebuildable **cache**, never a source of truth:
# MAGIC
# MAGIC 1. **Incremental maintenance** — each arriving batch of increments is aggregated and `MERGE`d
# MAGIC    into the current-state table (counts add; new bins insert; corrections subtract).
# MAGIC 2. **Rebuild from fact** — recompute the whole table from the immutable increment fact. This is
# MAGIC    the disaster-recovery path.
# MAGIC 3. **Consistency assertion** — the incrementally-maintained table must equal the rebuild. If it
# MAGIC    ever drifts, rebuild from the fact and you are correct again.
# MAGIC
# MAGIC The append-only fact is unchanged; point-in-time queries still replay it. This only adds a fast
# MAGIC read model on top.

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, DoubleType

CATALOG, SCHEMA = "workspace", "binmoments"
FACT    = f"{CATALOG}.{SCHEMA}.increment_fact"        # append-only signed deltas (input)
CURRENT = f"{CATALOG}.{SCHEMA}.histogram_current"     # materialized current state (this notebook)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Input prep — a small append-only increment fact
# MAGIC In production the increment fact is produced upstream (the package assigns each reading to a bin
# MAGIC and emits a signed delta). Here we synthesise a tiny pre-binned fact so the notebook is
# MAGIC self-contained. The star of this notebook is the **maintenance**, not the bin assignment
# MAGIC (distributing bin assignment is fenced in ADR-010).

# COMMAND ----------

fact_schema = StructType([
    StructField("instrument_id", StringType()),
    StructField("bin_schema_id", StringType()),
    StructField("event_hour",    StringType()),
    StructField("bin_index",     IntegerType()),
    StructField("count_delta",   DoubleType()),   # +1 per reading; corrections add -1 / +1
    StructField("arrival_time",  StringType()),   # transaction time (kept; not used by current state)
])

rows = [
    # two hours of readings for one instrument, schema S1
    ("TEMP-001", "S1", "2024-06-10T00", 3, 1.0, "2024-06-10T00:00:05"),
    ("TEMP-001", "S1", "2024-06-10T00", 3, 1.0, "2024-06-10T00:05:05"),
    ("TEMP-001", "S1", "2024-06-10T00", 4, 1.0, "2024-06-10T00:10:05"),
    ("TEMP-001", "S1", "2024-06-10T01", 5, 1.0, "2024-06-10T01:00:05"),
    ("TEMP-001", "S1", "2024-06-10T01", 5, 1.0, "2024-06-10T01:05:05"),
    # a late CORRECTION arriving later: that 00:10 reading was really bin 6, not 4
    ("TEMP-001", "S1", "2024-06-10T00", 4, -1.0, "2024-06-12T09:00:00"),  # retract bin 4
    ("TEMP-001", "S1", "2024-06-10T00", 6,  1.0, "2024-06-12T09:00:00"),  # assert bin 6
]
spark.createDataFrame(rows, fact_schema) \
     .write.format("delta").mode("overwrite").saveAsTable(FACT)
print(f"increment fact rows: {spark.table(FACT).count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Create the (empty) current-state table

# COMMAND ----------

spark.sql(f"DROP TABLE IF EXISTS {CURRENT}")
spark.sql(f"""
    CREATE TABLE {CURRENT} (
        instrument_id STRING,
        bin_schema_id STRING,
        event_hour    STRING,
        bin_index     INT,
        count         DOUBLE
    ) USING delta
""")
print(f"created {CURRENT}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Incremental maintenance — MERGE a batch of increments
# MAGIC Aggregate the batch by key, then upsert: existing bins get their count incremented by the
# MAGIC batch delta; unseen bins are inserted. This is the path that runs as new data arrives.

# COMMAND ----------

def merge_increment_batch(batch_df):
    """Aggregate signed deltas by key and MERGE into the current-state table."""
    agg = (batch_df
           .groupBy("instrument_id", "bin_schema_id", "event_hour", "bin_index")
           .agg(F.sum("count_delta").alias("delta")))
    agg.createOrReplaceTempView("batch_agg")
    spark.sql(f"""
        MERGE INTO {CURRENT} t
        USING batch_agg s
          ON  t.instrument_id = s.instrument_id
          AND t.bin_schema_id = s.bin_schema_id
          AND t.event_hour    = s.event_hour
          AND t.bin_index     = s.bin_index
        WHEN MATCHED THEN UPDATE SET t.count = t.count + s.delta
        WHEN NOT MATCHED THEN INSERT (instrument_id, bin_schema_id, event_hour, bin_index, count)
                          VALUES (s.instrument_id, s.bin_schema_id, s.event_hour, s.bin_index, s.delta)
    """)

fact = spark.table(FACT)

# Process the fact as two arriving batches (original readings, then the later correction)
# to exercise incremental maintenance the way streaming ingestion would.
original   = fact.filter(F.col("arrival_time") < "2024-06-11")
correction = fact.filter(F.col("arrival_time") >= "2024-06-11")

merge_increment_batch(original)
print("after original batch:")
spark.table(CURRENT).orderBy("event_hour", "bin_index").show(truncate=False)

merge_increment_batch(correction)
print("after correction batch (bin 4 retracted, bin 6 asserted):")
spark.table(CURRENT).filter("count != 0").orderBy("event_hour", "bin_index").show(truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Rebuild from the fact — the safety net
# MAGIC Recompute the whole current state directly from the immutable fact. The materialized table is
# MAGIC correct only if it equals this.

# COMMAND ----------

rebuild = (fact
           .groupBy("instrument_id", "bin_schema_id", "event_hour", "bin_index")
           .agg(F.sum("count_delta").alias("count"))
           .filter("count != 0"))
print("rebuild from fact:")
rebuild.orderBy("event_hour", "bin_index").show(truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Consistency assertion — incremental must equal rebuild

# COMMAND ----------

maintained = spark.table(CURRENT).filter("count != 0")

# Symmetric difference on all columns must be empty.
diff = maintained.exceptAll(rebuild).unionAll(rebuild.exceptAll(maintained))
mismatch = diff.count()
print(f"rows where maintained and rebuild disagree: {mismatch}")
assert mismatch == 0, "VALIDATION FAILED — materialized current state drifted from the fact"
print("VALIDATED: incrementally-maintained current state matches a full rebuild from the fact.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Fast read — the whole point
# MAGIC The current histogram for an instrument is now a single filtered read, no delta replay.

# COMMAND ----------

(spark.table(CURRENT)
      .filter("instrument_id = 'TEMP-001' AND bin_schema_id = 'S1' AND count != 0")
      .groupBy("bin_index").agg(F.sum("count").alias("total_count"))
      .orderBy("bin_index")
      .show(truncate=False))
