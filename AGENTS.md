# Dspx-Monitor Agent Notes

## Project Snapshot
- Streamlit dashboard for monitoring Despereaux cryogenic dilution refrigerator data.
- Current working branch initialized for this session: `dev/streamlit-latest`.
- Main modules are flat Python files: `app.py`, `core.py`, and `scheduler.py`.
- `core.py` owns shared constants, data loading, Slack report helpers, log paths, and refresh-signal utilities.
- `app.py` renders the Streamlit UI and imports shared behavior from `core.py`.
- `scheduler.py` runs background checks, refresh signaling, and scheduled Slack reports.

## Environment Setup
- Use uv for local setup.
- Create the default uv virtual environment with:
  ```bash
  uv venv
  ```
- In this workspace sandbox, uv may need a repo-local cache:
  ```bash
  UV_CACHE_DIR=.uv-cache uv venv
  UV_CACHE_DIR=.uv-cache uv pip install -e .
  ```
- Activate the environment with:
  ```bash
  source .venv/bin/activate
  ```
- Package metadata currently supports Python `>=3.11` so uv's default CPython interpreter can install the app.

## Run Commands
- Dashboard:
  ```bash
  streamlit run app.py --server.port 8501
  ```
- Installed entry point:
  ```bash
  dspx-monitor
  ```
- Scheduler:
  ```bash
  python scheduler.py
  ```
- Tests, when present:
  ```bash
  pytest
  ```

## Data, Secrets, and Generated Files
- The app reads TSV data from `data/`, usually a symlink to refrigerator log storage.
- Data filenames are expected to use `MMDDYY.txt`.
- Do not commit fridge data, `logs/`, `.refresh_signal`, `.venv/`, `.uv-cache/`, or secret/token files.
- Slack secrets are loaded from environment variables first, then `slack.secret`.
- Expected Slack keys include `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, and `SLACK_SIGNING_SECRET`.
- Scheduler report targets use `SLACK_REPORT_CHANNEL` or `SLACK_REPORT_USER`.

## Development Notes
- Prefer changing shared data parsing, constants, and Slack report behavior in `core.py`.
- Keep Streamlit-specific rendering concerns in `app.py`.
- Keep scheduled/background-loop behavior in `scheduler.py`.
- Be careful with import-time side effects: importing `app.py` initializes logging and touches Streamlit state.
- Keep `README.md` up to date when setup, dependencies, run commands, data expectations, or user-facing behavior changes.
- The README may lag package metadata; verify Python and dependency requirements against `setup.py` before changing setup instructions.
- Preserve compatibility with the installed editable package. If a top-level Python file is imported by another module, include it in `py_modules` in `setup.py`.
