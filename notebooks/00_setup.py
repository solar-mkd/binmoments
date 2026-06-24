# Databricks notebook source
# MAGIC %md
# MAGIC # BinMoments — Setup
# MAGIC
# MAGIC Makes the `binmoments` package importable on serverless compute. The other notebooks
# MAGIC start by running this with `%run ./00_setup`.
# MAGIC
# MAGIC The repo root is derived from this notebook's own location, so it works in **any** user's
# MAGIC workspace without editing a hard-coded path — which is what lets a reviewer clone the repo
# MAGIC and run it unchanged.

# COMMAND ----------

import os
import sys

# Discover the repo root from this notebook's path, e.g.
#   /Users/<you>/binmoments/notebooks/00_setup  ->  /Workspace/Users/<you>/binmoments
_nb_path = (
    dbutils.notebook.entry_point.getDbutils()
    .notebook().getContext().notebookPath().get()
)
_repo_root = "/Workspace" + "/".join(_nb_path.split("/")[:-2])  # drop "notebooks/<name>"
_src = _repo_root + "/src"

if not os.path.exists(_src):
    raise RuntimeError(
        f"Could not locate the package source at {_src}. "
        f"If your repo lives elsewhere, set _src manually to <repo>/src."
    )

# Put the package source FIRST so it wins over any same-named folder on the path.
if _src in sys.path:
    sys.path.remove(_src)
sys.path.insert(0, _src)

import binmoments

print("binmoments ready from:", binmoments.__file__)
