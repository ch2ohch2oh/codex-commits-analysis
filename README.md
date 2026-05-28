# Commit & PR Trend Analysis

A `uv`-managed Python project that renders a 3-panel weekly trend chart (lines changed, PRs per week, median PR size with IQR) from any git repository using seaborn and matplotlib.

The repo includes two git submodules under `repos/` for ready-to-analyze data:

- [`openai/codex`](https://github.com/openai/codex) — AI coding agent
- [`microsoft/vscode`](https://github.com/microsoft/vscode) — Code editor

## What it measures

- **Commits & churn**: count of commits and significant lines changed (additions + deletions from `git log --numstat -w`, which ignores whitespace-only changes).
- **PR metrics** (estimated from git history, not the GitHub API): the script analyzes `main --first-parent` and treats commits whose subject contains a PR number like `(#12345)` as merged PRs. PR size is the added + deleted lines from `git log --numstat -w` for that commit.

This heuristic works well for repos that use squash merges; it will undercount or misclassify PRs under other merge styles.

## Run it

```bash
# Analyze the codex repo (default)
uv run git-weekly-trends

# Analyze another repo
uv run git-weekly-trends --repo repos/vscode --repo-label vscode --rev-spec "main --after=2023-01-01"
```

This writes a 3-panel chart SVG and a combined CSV (commit + PR data) that can be reused to regenerate the chart without re-scanning git history. Redraw from a saved CSV:

```bash
uv run git-weekly-trends \
  --main-chart-only \
  --metrics-csv-input output/codex_weekly_report_data.csv
```

## Codex — openai/codex

Event markers: GPT-5.2-Codex (Dec 2025), Codex app + GPT-5.3-Codex (Feb 2026).

![Codex weekly trends](output/codex_weekly_metrics.svg)

### Notes on the data

Nine weeks exceeded 500,000 significant lines changed. Most of these spikes are from vendored/generated code churn or large-scale refactors, not from a proportional increase in hand-written engineering work.

| Week | Lines | Dominant change | Share |
|---|---|---|---|
| 2026-01-26 | 1,126,159 | Vendored protocol schema fixtures (80% `.json`) | Top 5 commits: 36% |
| 2026-02-16 | 597,938 | Removing generated v1 JSON schema codegen | Top 5 commits: 38% |
| 2026-03-09 | 935,749 | Moving TUI onto app-server + relocating unit tests (`.rs`) | Top 5 commits: 44% |
| 2026-03-16 | 600,456 | Extracting capabilities, sandbox, and orchestrator crates | Distributed |
| 2026-03-23 | 850,211 | Unifying TUI on app-server, deleting legacy TUI (145K lines removed) | Top 5 commits: 51% |
| 2026-04-20 | 962,434 | OAuth refactor, rollout trace crate, feature flag removals | Distributed (8%) |
| 2026-04-27 | 606,286 | App-server request-processor split, proto changes | Distributed |
| 2026-05-11 | 805,254 | TUI module splits, diagnostics, permissions refactor | Distributed (6%) |
| 2026-05-25 | 1,246,274 | Swapping vendored SQLite amalgamation (84% `.c`) | 2 commits: 93% |

**Vendored code** (Jan 26, Feb 16, May 25) — Generated protobuf schema files, vendored C dependencies, and codegen outputs produce large line counts from simple add/remove operations. The May 25 spike is two commits: one deleting the old SQLite amalgamation (582K lines) and one adding the fixed version (582K lines).

**Large refactors** (Mar 9, Mar 23) — The TUI was migrated onto an app-server architecture. In Mar 23 alone, 145K lines of legacy TUI code were deleted. These are true engineering work but concentrated deletions rather than sustained output.

**High-activity weeks** (Mar 16, Apr 20, Apr 27, May 11) — Top commits account for only 6–14% of total lines, meaning the churn was spread across many smaller changes typical of a busy engineering team.

## VS Code — microsoft/vscode

Analysis covers `main` from 2023 onwards (53,932 commits, 185 weeks). Event marker: Hello Copilot (Jun 2025).

![VS Code weekly trends](output/vscode_weekly_metrics.svg)

### Notes on the data

| Week | Lines | Dominant change | Share |
|---|---|---|---|
| 2025-06-23 | 937,622 | "Hello Copilot" — large initial Copilot code check-in (`.ts`, `.json`) | 1 commit: 96% |
| 2024-04-15 | 233,462 | Merge commits inflating counts (merge of `chat-agent-hover` branch) | Top 3 commits: 95% |

The same categories from codex apply: large feature drops (Hello Copilot) and merge artifacts (2024). The PR detection heuristic (`#12345` in subject) may undercount if MS uses a different merge style where PR numbers don't always appear in first-parent subjects.

## Useful variations

```bash
uv run git-weekly-trends --rev-spec main
uv run git-weekly-trends --rev-spec "main --first-parent"
uv run python scripts/analyze_repo_history.py
```

Writes the 3-panel chart SVG and a combined CSV (commit + PR data) that can be reused to regenerate the chart without re-scanning git history:

- [`output/codex_weekly_report_data.csv`](output/codex_weekly_report_data.csv)
- [`output/codex_weekly_metrics.svg`](output/codex_weekly_metrics.svg)

![Weekly engineering activity chart](output/codex_weekly_metrics.svg)

Redraw the chart from a previously saved CSV:

```bash
uv run git-weekly-trends \
  --main-chart-only \
  --metrics-csv-input output/codex_weekly_report_data.csv
```

## Notes on the data

Nine weeks exceeded 500,000 significant lines changed. Most of these spikes are from vendored/generated code churn or large-scale refactors, not from a proportional increase in hand-written engineering work.

| Week | Lines | Dominant change | Share |
|---|---|---|---|
| 2026-01-26 | 1,126,159 | Vendored protocol schema fixtures (80% `.json`) | Top 5 commits: 36% |
| 2026-02-16 | 597,938 | Removing generated v1 JSON schema codegen | Top 5 commits: 38% |
| 2026-03-09 | 935,749 | Moving TUI onto app-server + relocating unit tests (`.rs`) | Top 5 commits: 44% |
| 2026-03-16 | 600,456 | Extracting capabilities, sandbox, and orchestrator crates | Distributed |
| 2026-03-23 | 850,211 | Unifying TUI on app-server, deleting legacy TUI (145K lines removed) | Top 5 commits: 51% |
| 2026-04-20 | 962,434 | OAuth refactor, rollout trace crate, feature flag removals | Distributed (8%) |
| 2026-04-27 | 606,286 | App-server request-processor split, proto changes | Distributed |
| 2026-05-11 | 805,254 | TUI module splits, diagnostics, permissions refactor | Distributed (6%) |
| 2026-05-25 | 1,246,274 | Swapping vendored SQLite amalgamation (84% `.c`) | 2 commits: 93% |

**Vendored code** (Jan 26, Feb 16, May 25) — Generated protobuf schema files, vendored C dependencies, and codegen outputs produce large line counts from simple add/remove operations. The May 25 spike is two commits: one deleting the old SQLite amalgamation (582K lines) and one adding the fixed version (582K lines).

**Large refactors** (Mar 9, Mar 23) — The TUI was migrated onto an app-server architecture. In Mar 23 alone, 145K lines of legacy TUI code were deleted. These are true engineering work but concentrated deletions rather than sustained output.

**High-activity weeks** (Mar 16, Apr 20, Apr 27, May 11) — Top commits account for only 6–14% of total lines, meaning the churn was spread across many smaller changes typical of a busy engineering team.

## Useful variations

Analyze only the main branch:

```bash
uv run git-weekly-trends --rev-spec main
```

Analyze the first-parent history of main:

```bash
uv run git-weekly-trends --rev-spec "main --first-parent"
```

The legacy wrapper still works if you want a direct script path:

```bash
uv run python scripts/analyze_repo_history.py
```
