# Databricks notebook source
# MAGIC %md
# MAGIC # 04 — Plot Histograms (scenario-aware)
# MAGIC
# MAGIC Plots per-hour histograms from the `histogram_plot` view (bin **edges**, empty bins as 0). It
# MAGIC reads the `ground_truth` table to auto-pick a **clean** hour and a **drift** hour for the
# MAGIC overlay, so the chart illustrates whatever scenario is active: a mean shift moves the
# MAGIC distribution sideways; a variance inflation widens it in place.
# MAGIC
# MAGIC **Run order:** `05` → `01` → `02` → `04` (02 builds the histogram and view).

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

CATALOG, SCHEMA = "workspace", "binmoments"
PLOT_VIEW    = f"{CATALOG}.{SCHEMA}.histogram_plot"
GROUND_TRUTH = f"{CATALOG}.{SCHEMA}.ground_truth"

# Auto-pick a drift hour (inside the first fault) and a clean hour (well before it) from ground truth.
gt = spark.table(GROUND_TRUTH).orderBy("start").toPandas()
first_start = pd.to_datetime(gt["start"].iloc[0])
DRIFT_HOUR = first_start.strftime("%Y-%m-%dT14")                       # 2pm on the first drift day
CLEAN_HOUR = (first_start - pd.Timedelta(days=20)).strftime("%Y-%m-%dT14")  # 2pm, 20 days earlier
SINGLE_HOUR = DRIFT_HOUR                                               # change to any 'YYYY-MM-DDTHH'
print(f"fault kind: {gt['kind'].iloc[0]}   clean hour: {CLEAN_HOUR}   drift hour: {DRIFT_HOUR}")

# COMMAND ----------

def load_hour(instrument_id, event_hour):
    return (spark.sql(f"""
        SELECT bin_index, lower_edge, upper_edge, midpoint, count
        FROM {PLOT_VIEW}
        WHERE instrument_id = '{instrument_id}' AND event_hour = '{event_hour}'
        ORDER BY bin_index
    """).toPandas())

def finite_widths(df):
    w = (df["upper_edge"] - df["lower_edge"]).to_numpy(dtype=float)
    med = np.median(w[np.isfinite(w)]) if np.isfinite(w).any() else 1.0
    w[~np.isfinite(w)] = med
    return w

INSTRUMENT = "TEMP-001"

# COMMAND ----------

# MAGIC %md
# MAGIC ### Single hour

# COMMAND ----------

df = load_hour(INSTRUMENT, SINGLE_HOUR)
if df.empty:
    print(f"No data for {INSTRUMENT} at {SINGLE_HOUR}. Has 02 run for the active scenario?")
else:
    w = finite_widths(df)
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.bar(df["midpoint"], df["count"], width=w * 0.95, align="center",
           color="#2C5F8A", edgecolor="white", linewidth=0.5)
    ax.set_xlabel("temperature (°C)"); ax.set_ylabel("count")
    ax.set_title(f"{INSTRUMENT} — histogram for {SINGLE_HOUR}")
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout(); plt.show()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Clean hour vs drift hour — the fault made visible

# COMMAND ----------

clean = load_hour(INSTRUMENT, CLEAN_HOUR)
drift = load_hour(INSTRUMENT, DRIFT_HOUR)
if clean.empty or drift.empty:
    print("Need both hours present; adjust CLEAN_HOUR / DRIFT_HOUR above.")
else:
    w = finite_widths(clean)
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.bar(clean["midpoint"], clean["count"], width=w * 0.95, align="center",
           color="#2C5F8A", alpha=0.55, edgecolor="white", linewidth=0.4, label=f"clean ({CLEAN_HOUR})")
    ax.bar(drift["midpoint"], drift["count"], width=w * 0.95, align="center",
           color="#C0392B", alpha=0.55, edgecolor="white", linewidth=0.4, label=f"drift ({DRIFT_HOUR})")
    ax.set_xlabel("temperature (°C)"); ax.set_ylabel("count")
    ax.set_title(f"{INSTRUMENT} — clean vs drift hour ({gt['kind'].iloc[0]})")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(); plt.tight_layout(); plt.show()

# COMMAND ----------

# MAGIC %md
# MAGIC A **mean shift** moves the red distribution sideways from the blue (the displacement Wasserstein
# MAGIC measures). A **variance inflation** keeps the center but spreads the red wider — same mean, fatter
# MAGIC tails — which a mean-threshold monitor would miss entirely.
