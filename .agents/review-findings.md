# Review Findings

These findings came from the reviewer output for the current branch and should be resolved before considering the patch fully correct.

## P2: Preserve configured Slack destinations

- File: `run.bat`
- Line: 10
- Issue: The Windows launcher unconditionally assigns `SLACK_REPORT_CHANNEL`, overriding an operator's preconfigured `SLACK_REPORT_CHANNEL` or `SLACK_REPORT_USER` and forcing scheduler reports/alerts to `#despereaux`.
- Recommendation: Only provide a default destination when no destination is configured, or leave routing configuration entirely to the environment.

## P2: Avoid terminating unrelated scheduler.py processes

- File: `run.bat`
- Line: 38
- Issue: On Windows, the `wmic` query terminates every `python.exe` process whose command line contains `scheduler.py`, not just the scheduler started by the batch file.
- Recommendation: Track the child process started by the launcher or use a more specific identifier so stopping this dashboard cannot kill unrelated scheduler processes.

## P2: Format pressure fallback text in scientific notation

- File: `core.py`
- Lines: 432-433
- Issue: Plain-text Slack fallback formatting uses `:.2f` for pressure channels, turning small values like `3.4e-5` into `0.00`. Slack block rendering uses scientific notation, but fallback/mobile/search text remains misleading.
- Recommendation: Format pressure fallback values in scientific notation to match the block content.
