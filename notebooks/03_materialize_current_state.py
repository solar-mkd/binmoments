# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Materialize the Current-State Histogram
# MAGIC
# MAGIC Maintains a fast **current-state** read model over the silver `increment_fact` from notebook 02.
# MAGIC This is collapsed to one net count per **(instrument, schema, bin)** — the instrument's whole
# MAGIC current distribution, summed over all hours and including all corrections (ADR-020 option A).
# MAGIC
# MAGIC This is a *different grain* from the gold per-hour `histogram` table:
# MAGIC - `histogram` answers "what did the distribution look like in **each hour**?" (index to the hour)
# MAGIC - `histogram_current` answers "what is this instrument's distribution **right now**?" (one read)
# MAGIC
# MAGIC The append-only fact is unchanged; this adds a rebuildable cache.
# MAGIC
# MAGIC 1. **Incremental maintenance** — `MERGE` the fact in per-day batches; counts add, new bins insert.
# MAGIC 2. **Rebuild from fact** — recompute from the immutable fact (the DR path).
# MAGIC 3. **Consistency assertion** — the maintained table must equal the rebuild.
# MAGIC
# MAGIC **Run order:** run `01` then `02` first (02 writes the fact).

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

from pyspark.sql import functions as F

CATALOG, SCHEMA = "workspace", "binmoments"
FACT    = f"{CATALOG}.{SCHEMA}.increment_fact"        # silver, written by notebook 02
CURRENT = f"{CATALOG}.{SCHEMA}.histogram_current"     # collapsed current state (this notebook)

fact = spark.table(FACT)
print(f"increment_fact rows: {fact.count()}")

# COMMAND ----------

# Re-runnable: the current state is always rebuilt from the immutable fact.
spark.sql(f"DROP TABLE IF EXISTS {CURRENT}")
spark.sql(f"""
    CREATE TABLE {CURRENT} (
        instrument_id STRING,
        bin_schema_id STRING,
        bin_index     INT,
        count         DOUBLE
    ) USING delta
""")
print(f"created {CURRENT} (grain: instrument, schema, bin)")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Incremental maintenance — MERGE the fact in per-day batches
# MAGIC The hour dimension is summed away in the aggregation; the merge key is (instrument, schema, bin).

# COMMAND ----------

def merge_batch(batch_df):
    """Aggregate signed deltas to the collapsed grain and upsert."""
    (batch_df
     .groupBy("instrument_id", "bin_schema_id", "bin_index")
     .agg(F.sum("count_delta").alias("delta"))
     .createOrReplaceTempView("batch_agg"))
    spark.sql(f"""
        MERGE INTO {CURRENT} t
        USING batch_agg s
          ON  t.instrument_id = s.instrument_id
          AND t.bin_schema_id = s.bin_schema_id
          AND t.bin_index     = s.bin_index
        WHEN MATCHED THEN UPDATE SET t.count = t.count + s.delta
        WHEN NOT MATCHED THEN INSERT (instrument_id, bin_schema_id, bin_index, count)
                          VALUES (s.instrument_id, s.bin_schema_id, s.bin_index, s.delta)
    """)

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
           .groupBy("instrument_id", "bin_schema_id", "bin_index")
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
# MAGIC ### Fast read — the instrument's current distribution, one query, no replay

# COMMAND ----------

(spark.table(CURRENT)
   .filter("count != 0")
   .orderBy("instrument_id", "bin_index")
   .show(15, truncate=False))

# COMMAND ----------

# MAGIC %md
# MAGIC Corrections are appended compensating deltas in the fact (retract = negative delta, assert =
# MAGIC positive delta); they `MERGE` in identically and the rebuild stays consistent. Proven in
# MAGIC `tests/test_serving.py` and recorded in ADR-020.
