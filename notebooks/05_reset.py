# Databricks notebook source
# MAGIC %md
# MAGIC # 05 — Reset
# MAGIC
# MAGIC Drops every table and view the pipeline creates, for a clean-slate validation run. Everything
# MAGIC is regenerable from code (the simulator is seeded), so this loses nothing — `01` rebuilds the
# MAGIC same data deterministically.
# MAGIC
# MAGIC **Workflow:** run this, then `01 → 02 → 03 → 04`.

# COMMAND ----------

CATALOG, SCHEMA = "workspace", "binmoments"

TABLES = [
    "bronze_readings",     # bronze
    "ground_truth",        # injected-fault log (scoring only)
    "increment_fact",      # silver
    "histogram",           # gold (per-hour)
    "fingerprints",        # gold
    "bin_schema",          # gold (bin edges)
    "histogram_current",   # serving read model
]
VIEWS = ["histogram_plot"]

for t in TABLES:
    spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.{SCHEMA}.{t}")
    print(f"dropped table {t}")
for v in VIEWS:
    spark.sql(f"DROP VIEW IF EXISTS {CATALOG}.{SCHEMA}.{v}")
    print(f"dropped view  {v}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Confirm the schema is empty

# COMMAND ----------

display(spark.sql(f"SHOW TABLES IN {CATALOG}.{SCHEMA}"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Clear in-memory Python state (optional)
# MAGIC Uncomment to also restart the Python interpreter — clears all variables and imported modules.
# MAGIC Note this restarts the session, so run it on its own.

# COMMAND ----------

# dbutils.library.restartPython()
