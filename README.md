# Codex Commit Analysis

This workspace contains the `openai/codex` repository as a git submodule plus a small `uv`-managed Python project that renders a 3-panel weekly trend chart (lines changed, PRs per week, median PR size with IQR) using seaborn and matplotlib.

## What it measures

- **Commits & churn**: count of commits and significant lines changed (additions + deletions from `git log --numstat -w`, which ignores whitespace-only changes).
- **PR metrics** (estimated from git history, not the GitHub API): the script analyzes `main --first-parent` and treats commits whose subject contains a PR number like `(#12345)` as merged PRs. PR size is the added + deleted lines from `git log --numstat -w` for that commit.

This heuristic works well for repos that use squash merges; it will undercount or misclassify PRs under other merge styles.

## Run it

```bash
uv run codex-commit-analysis
```

Writes the 3-panel chart SVG and a combined CSV (commit + PR data) that can be reused to regenerate the chart without re-scanning git history:

- [`output/codex_weekly_report_data.csv`](output/codex_weekly_report_data.csv)
- [`output/codex_weekly_metrics.svg`](output/codex_weekly_metrics.svg)

![Weekly engineering activity chart](output/codex_weekly_metrics.svg)

Redraw the chart from a previously saved CSV:

```bash
uv run codex-commit-analysis \
  --main-chart-only \
  --metrics-csv-input output/codex_weekly_report_data.csv
```

## Useful variations

Analyze only the main branch:

```bash
uv run codex-commit-analysis --rev-spec main
```

Analyze the first-parent history of main:

```bash
uv run codex-commit-analysis --rev-spec "main --first-parent"
```

The legacy wrapper still works if you want a direct script path:

```bash
uv run python scripts/analyze_repo_history.py
```
