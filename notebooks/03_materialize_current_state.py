# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Materialize the Current-State Histogram
# MAGIC
# MAGIC Maintains a fast **current-state** read model over the silver `increment_fact` that notebook 02
# MAGIC writes. The append-only fact is unchanged; this adds a rebuildable cache for "latest state"
# MAGIC reads (ADR-020).
# MAGIC
# MAGIC 1. **Incremental maintenance** — `MERGE` the fact in per-day batches (as streaming ingestion
# MAGIC    would), counts add, new bins insert.
# MAGIC 2. **Rebuild from fact** — recompute the whole table from the immutable fact (the DR path).
# MAGIC 3. **Consistency assertion** — the maintained table must equal the rebuild.
# MAGIC
# MAGIC **Run order:** run `01_ingest_bronze` then `02_fingerprint_and_drift` first (02 writes the fact).

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

from pyspark.sql import functions as F

CATALOG, SCHEMA = "workspace", "binmoments"
FACT    = f"{CATALOG}.{SCHEMA}.increment_fact"        # silver, written by notebook 02
CURRENT = f"{CATALOG}.{SCHEMA}.histogram_current"     # materialized current state (this notebook)

fact = spark.table(FACT)
print(f"increment_fact rows: {fact.count()}")

# COMMAND ----------

# Create the current-state table fresh (re-runnable: it is always rebuilt from the immutable fact).
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
# MAGIC ### Incremental maintenance — MERGE the fact in per-day batches

# COMMAND ----------

def merge_batch(batch_df):
    """Aggregate signed deltas by key and upsert into the current-state table."""
    (batch_df
     .groupBy("instrument_id", "bin_schema_id", "event_hour", "bin_index")
     .agg(F.sum("count_delta").alias("delta"))
     .createOrReplaceTempView("batch_agg"))
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

# Process the fact one day at a time, the way streaming ingestion would arrive.
fact_d = fact.withColumn("day", F.substring("event_hour", 1, 10))
day_list = [r["day"] for r in fact_d.select("day").distinct().orderBy("day").collect()]
for d in day_list:
    merge_batch(fact_d.filter(F.col("day") == d))
print(f"current-state rows after maintenance: {spark.table(CURRENT).filter('count != 0').count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Rebuild from the fact + consistency assertion

# COMMAND ----------

rebuild = (fact
           .groupBy("instrument_id", "bin_schema_id", "event_hour", "bin_index")
           .agg(F.sum("count_delta").alias("count"))
           .filter("count != 0"))
maintained = spark.table(CURRENT).filter("count != 0").select(rebuild.columns)

diff = maintained.exceptAll(rebuild).unionAll(rebuild.exceptAll(maintained))
mismatch = diff.count()
print(f"rows where maintained and rebuild disagree: {mismatch}")
assert mismatch == 0, "VALIDATION FAILED — materialized current state drifted from the fact"
print("VALIDATED: incrementally-maintained current state matches a full rebuild from the fact.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Fast read — current distribution for the instrument, no delta replay

# COMMAND ----------

(spark.table(CURRENT)
   .filter("count != 0")
   .groupBy("instrument_id", "bin_index")
   .agg(F.sum("count").alias("total_count"))
   .orderBy("instrument_id", "bin_index")
   .show(12, truncate=False))

# COMMAND ----------

# MAGIC %md
# MAGIC Corrections are appended compensating deltas in the fact (retract = negative delta, assert =
# MAGIC positive delta); they `MERGE` in identically and the rebuild stays consistent. This is proven
# MAGIC in `tests/test_current_state.py` and recorded in ADR-020.
