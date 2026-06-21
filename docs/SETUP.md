# Setup

This project is developed **locally** (VS Code + a Python virtual environment) and
**executed on Databricks Free Edition**. The local repo is the source of truth; Databricks
is the runtime. Logic lives in `src/binmoments/` as plain, testable PySpark; the
`notebooks/` are thin Databricks entry points that import the package.

## Prerequisites

- Python 3.10+ (`python --version`)
- Git
- VS Code (open this folder; accept the recommended extensions when prompted)
- A Databricks Free Edition account (for execution; not needed for local tests)

## 1. Create and activate a virtual environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```
If activation is blocked, allow it for this session:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

**Windows (cmd):**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 2. Install dependencies (editable install of the package)

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

## 3. Run the tests

```bash
pytest
```
You should see the smoke test pass. That confirms the package imports and the harness is
wired. Real tests arrive with the vertical slice.

## 4. VS Code

- Select the interpreter: Command Palette -> "Python: Select Interpreter" -> the `.venv`.
- The Testing panel will discover `pytest` tests (configured in `.vscode/settings.json`).

## 5. Databricks execution (later)

When the vertical slice exists and you want to run it on real serverless compute:

- Install the **Databricks** VS Code extension (already in the recommended list).
- Install a `databricks-connect` version that **matches your Free Edition serverless
  runtime** — check the current docs, as the version must align with the runtime:
  https://docs.databricks.com/dev-tools/vscode-ext.html
- Do NOT pin `databricks-connect` in `requirements.txt`; install it separately to avoid
  conflicting with the local `pyspark`. Consider a separate environment if needed.

Free Edition notes that shape how the slice runs (see ADR-010): serverless compute only;
run Structured Streaming in **triggered/incremental** mode (`Trigger.AvailableNow` or
scheduled micro-batch), not always-on; keep synthetic data volumes modest to stay within
the fair-usage quota.

## Configuration

Copy the template and edit your real config (which is git-ignored):
```bash
cp config/instruments.example.yaml config/instruments.yaml   # macOS/Linux
copy config\instruments.example.yaml config\instruments.yaml  REM Windows cmd
```
Secrets are never stored in config — they are referenced from the platform secret store
(ADR-011).
