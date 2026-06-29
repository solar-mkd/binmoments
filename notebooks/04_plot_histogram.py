# Databricks notebook source
# MAGIC %md
# MAGIC # 04 — Plot Histograms
# MAGIC
# MAGIC Plots the per-hour histogram for an instrument from the `histogram_plot` view (bin **edges**,
# MAGIC empty bins as 0). Pick the instrument and hour with the widgets at the top. The second chart
# MAGIC overlays a clean day against a drift day for the same hour-of-day, so the injected drift is
# MAGIC visible as a rightward shift of the whole distribution — the thing the Wasserstein distance
# MAGIC measured in notebook 02.
# MAGIC
# MAGIC **Run order:** run `01` and `02` first (02 builds the histogram and the view).

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

import numpy as np
import matplotlib.pyplot as plt

CATALOG, SCHEMA = "workspace", "binmoments"
PLOT_VIEW = f"{CATALOG}.{SCHEMA}.histogram_plot"

dbutils.widgets.text("instrument_id", "TEMP-001")
dbutils.widgets.text("event_hour", "2024-06-28T14")
INSTRUMENT = dbutils.widgets.get("instrument_id")
EVENT_HOUR = dbutils.widgets.get("event_hour")

# COMMAND ----------

def load_hour(instrument_id, event_hour):
    """Pull one hour's histogram (all bins, zero-filled, with edges) to the driver."""
    return (spark.sql(f"""
        SELECT bin_index, lower_edge, upper_edge, midpoint, count
        FROM {PLOT_VIEW}
        WHERE instrument_id = '{instrument_id}' AND event_hour = '{event_hour}'
        ORDER BY bin_index
    """).toPandas())


def finite_widths(df):
    """Bar widths from edges, with non-finite (open outer) bins clamped to the
    median finite width so the plot renders."""
    w = (df["upper_edge"] - df["lower_edge"]).to_numpy(dtype=float)
    med = np.median(w[np.isfinite(w)]) if np.isfinite(w).any() else 1.0
    w[~np.isfinite(w)] = med
    return w

# COMMAND ----------

# MAGIC %md
# MAGIC ### Single hour

# COMMAND ----------

df = load_hour(INSTRUMENT, EVENT_HOUR)
if df.empty:
    print(f"No data for {INSTRUMENT} at {EVENT_HOUR}. Check the widgets / that 02 has run.")
else:
    widths = finite_widths(df)
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.bar(df["midpoint"], df["count"], width=widths * 0.95, align="center",
           color="#2C5F8A", edgecolor="white", linewidth=0.5)
    ax.set_xlabel("temperature (°C)")
    ax.set_ylabel("count")
    ax.set_title(f"{INSTRUMENT} — histogram for {EVENT_HOUR}")
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.show()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Clean day vs drift day (same hour-of-day) — the drift, made visible

# COMMAND ----------

CLEAN_HOUR = "2024-06-20T14"   # a quiet day
DRIFT_HOUR = "2024-06-28T14"   # inside the injected +4°C drift window (27–29 Jun)

clean = load_hour(INSTRUMENT, CLEAN_HOUR)
drift = load_hour(INSTRUMENT, DRIFT_HOUR)

if clean.empty or drift.empty:
    print("Need both hours present; adjust CLEAN_HOUR / DRIFT_HOUR to hours that exist.")
else:
    w = finite_widths(clean)
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.bar(clean["midpoint"], clean["count"], width=w * 0.95, align="center",
           color="#2C5F8A", alpha=0.55, edgecolor="white", linewidth=0.4,
           label=f"clean ({CLEAN_HOUR})")
    ax.bar(drift["midpoint"], drift["count"], width=w * 0.95, align="center",
           color="#C0392B", alpha=0.55, edgecolor="white", linewidth=0.4,
           label=f"drift ({DRIFT_HOUR})")
    ax.set_xlabel("temperature (°C)")
    ax.set_ylabel("count")
    ax.set_title(f"{INSTRUMENT} — clean vs drift hour (the distribution shifts right)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend()
    plt.tight_layout()
    plt.show()

# COMMAND ----------

# MAGIC %md
# MAGIC The red distribution sits to the right of the blue one by roughly the injected offset — exactly
# MAGIC the displacement the Wasserstein distance reported as the drift signal in notebook 02. A static
# MAGIC threshold on the mean might catch this; a distribution distance catches shape changes too.
