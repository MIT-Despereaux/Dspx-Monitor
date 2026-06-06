# Dspx-Monitor Agent Notes

## Project Snapshot
- Streamlit dashboard for monitoring Despereaux cryogenic dilution refrigerator data.
- Current working branch initialized for this session: `dev/streamlit-latest`.
- Main modules are flat Python files: `app.py`, `core.py`, and `scheduler.py`.
- `core.py` owns shared constants, data loading, Slack report helpers, log paths, and refresh-signal utilities.
- `app.py` renders the Streamlit UI and imports shared behavior from `core.py`.
- `scheduler.py` runs background checks, refresh signaling, and scheduled Slack reports.

## Environment Setup
- Prefer the repository-local `.venv` virtual environment for all Python commands.
- Create it explicitly with uv when it does not exist:
  ```bash
  uv venv .venv
  ```
- In this workspace sandbox, uv may need a repo-local cache:
  ```bash
  UV_CACHE_DIR=.uv-cache uv venv .venv
  UV_CACHE_DIR=.uv-cache uv pip install -e .
  ```
- Activate the environment with:
  ```bash
  source .venv/bin/activate
  ```
- If `.venv` is unavailable or the uv setup fails, look for the Conda environment
  named `dspx-mon`:
  ```bash
  conda env list
  conda activate dspx-mon
  ```
- If neither `.venv` nor the `dspx-mon` Conda environment can be used, stop and
  ask the user which Python environment to use.
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

## Conventions
- Use Gitmoji prefixes for commit messages and pull request titles when they
  clarify the intent of a change. Prefer the shortcode form for portability,
  for example `:sparkles: Add cleaning-cache notebook split`.
- For feature-release work, use:
  - `:sparkles:` for introducing or expanding user-facing features.
  - `:bookmark:` for release or version-tag commits.
  - `:white_check_mark:` for adding, updating, or fixing tests.
  - `:memo:` for documentation-only updates.
  - `:bug:` for bug fixes.
  - `:recycle:` for refactors with no intended behavior change.
  - `:wrench:` for configuration updates.
  - `:construction:` only for explicitly incomplete work-in-progress commits.
