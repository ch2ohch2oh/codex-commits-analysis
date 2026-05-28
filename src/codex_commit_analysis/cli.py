from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import pandas as pd
import seaborn as sns

PR_NUMBER_RE = re.compile(r"\(#(\d+)\)")


@dataclass
class WeeklyStats:
    commits: int = 0
    additions: int = 0
    deletions: int = 0

    @property
    def significant_lines_changed(self) -> int:
        return self.additions + self.deletions


@dataclass
class WeeklyPrStats:
    prs: int = 0
    total_size: int = 0
    max_size: int = 0
    pr_sizes: list[int] = field(default_factory=list)

    @property
    def average_size(self) -> float:
        return self.total_size / self.prs if self.prs else 0.0

    @property
    def median_size(self) -> float:
        if not self.pr_sizes:
            return 0.0
        values = sorted(self.pr_sizes)
        mid = len(values) // 2
        if len(values) % 2:
            return float(values[mid])
        return (values[mid - 1] + values[mid]) / 2

    @property
    def q1_size(self) -> float:
        return percentile(self.pr_sizes, 25.0)

    @property
    def q3_size(self) -> float:
        return percentile(self.pr_sizes, 75.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze a git repository's history and summarize weekly commit "
            "counts and significant line changes."
        )
    )
    parser.add_argument(
        "--repo",
        default="codex",
        help="Path to the git repository to analyze. Defaults to the codex submodule.",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory where CSV and SVG artifacts will be written.",
    )
    parser.add_argument(
        "--rev-spec",
        default="--all",
        help=(
            "Revision selector passed to git log, such as --all, main, or "
            "main --first-parent. Defaults to --all."
        ),
    )
    parser.add_argument(
        "--metrics-csv-input",
        help=(
            "Read combined weekly metrics from an existing CSV instead of recomputing "
            "them from git history."
        ),
    )
    parser.add_argument(
        "--main-chart-only",
        action="store_true",
        help="Only regenerate the main chart from --metrics-csv-input and skip git history analysis.",
    )
    parser.add_argument(
        "--repo-label",
        help="Override the repo label used in chart titles.",
    )
    return parser.parse_args()


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def run_git_log(repo: Path, rev_spec: str, include_subject: bool = False) -> str:
    pretty = "--pretty=format:COMMIT\t%H\t%ad"
    if include_subject:
        pretty = "--pretty=format:COMMIT\t%H\t%ad\t%s"
    cmd = [
        "git",
        "-C",
        str(repo),
        "log",
        "--date=short",
        pretty,
        "--numstat",
        "-w",
    ]
    cmd.extend(rev_spec.split())
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout


def get_default_pr_rev_spec(repo: Path) -> str:
    main_ref = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", "main"],
        capture_output=True,
        text=True,
    )
    if main_ref.returncode == 0:
        return "main --first-parent"
    return "HEAD --first-parent"


def collect_weekly_stats(repo: Path, rev_spec: str) -> dict[date, WeeklyStats]:
    weekly: dict[date, WeeklyStats] = defaultdict(WeeklyStats)
    current_week: date | None = None

    for raw_line in run_git_log(repo, rev_spec).splitlines():
        if not raw_line:
            continue

        if raw_line.startswith("COMMIT\t"):
            _, _, date_text = raw_line.split("\t", 2)
            commit_date = datetime.strptime(date_text, "%Y-%m-%d").date()
            current_week = week_start(commit_date)
            weekly[current_week].commits += 1
            continue

        if current_week is None:
            continue

        parts = raw_line.split("\t", 2)
        if len(parts) < 3:
            continue

        added, deleted, _path = parts
        if added == "-" or deleted == "-":
            continue

        weekly[current_week].additions += int(added)
        weekly[current_week].deletions += int(deleted)

    return dict(sorted(weekly.items()))


def collect_weekly_pr_stats(repo: Path, rev_spec: str) -> dict[date, WeeklyPrStats]:
    weekly: dict[date, WeeklyPrStats] = defaultdict(WeeklyPrStats)
    current_week: date | None = None
    current_subject = ""
    current_size = 0

    def finalize_current() -> None:
        nonlocal current_week, current_subject, current_size
        if current_week is None:
            return
        if not PR_NUMBER_RE.search(current_subject):
            return
        stats = weekly[current_week]
        stats.prs += 1
        stats.total_size += current_size
        stats.max_size = max(stats.max_size, current_size)
        stats.pr_sizes.append(current_size)

    log_output = run_git_log(repo, rev_spec, include_subject=True)
    for raw_line in log_output.splitlines() + ["COMMIT\tEND\t1970-01-01\t"]:
        if not raw_line:
            continue

        if raw_line.startswith("COMMIT\t"):
            finalize_current()
            parts = raw_line.split("\t", 3)
            if len(parts) < 4:
                current_week = None
                current_subject = ""
                current_size = 0
                continue
            _, _sha, date_text, subject = parts
            commit_date = datetime.strptime(date_text, "%Y-%m-%d").date()
            current_week = week_start(commit_date)
            current_subject = subject
            current_size = 0
            continue

        if current_week is None:
            continue

        parts = raw_line.split("\t", 2)
        if len(parts) < 3:
            continue

        added, deleted, _path = parts
        if added == "-" or deleted == "-":
            continue
        current_size += int(added) + int(deleted)

    return dict(sorted(weekly.items()))


def fill_missing_pr_weeks(
    weekly_prs: dict[date, WeeklyPrStats],
    all_weeks: list[date],
) -> dict[date, WeeklyPrStats]:
    return {week: weekly_prs.get(week, WeeklyPrStats()) for week in all_weeks}


def percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * (pct / 100.0)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def write_csv(
    weekly: dict[date, WeeklyStats],
    weekly_prs: dict[date, WeeklyPrStats],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "week_start",
                "commits",
                "significant_lines_changed",
                "additions",
                "deletions",
                "prs",
                "average_pr_size",
                "median_pr_size",
                "q1_pr_size",
                "q3_pr_size",
                "total_pr_size",
                "max_pr_size",
            ]
        )
        for week, stats in weekly.items():
            pr_stats = weekly_prs[week]
            writer.writerow(
                [
                    week.isoformat(),
                    stats.commits,
                    stats.significant_lines_changed,
                    stats.additions,
                    stats.deletions,
                    pr_stats.prs,
                    round(pr_stats.average_size, 2),
                    round(pr_stats.median_size, 2),
                    round(pr_stats.q1_size, 2),
                    round(pr_stats.q3_size, 2),
                    pr_stats.total_size,
                    pr_stats.max_size,
                ]
            )


def read_metrics_csv(input_path: Path) -> tuple[dict[date, WeeklyStats], dict[date, WeeklyPrStats]]:
    weekly: dict[date, WeeklyStats] = {}
    weekly_prs: dict[date, WeeklyPrStats] = {}
    with input_path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            week = datetime.strptime(row["week_start"], "%Y-%m-%d").date()
            weekly[week] = WeeklyStats(
                commits=int(row.get("commits", 0) or 0),
                additions=int(row["additions"]),
                deletions=int(row["deletions"]),
            )
            pr_stats = WeeklyPrStats(
                prs=int(row["prs"]),
                total_size=int(row["total_pr_size"]),
                max_size=int(row["max_pr_size"]),
            )
            median = float(row.get("median_pr_size", 0) or 0)
            q1 = float(row.get("q1_pr_size", 0) or 0)
            q3 = float(row.get("q3_pr_size", 0) or 0)
            if pr_stats.prs > 0:
                pr_stats.pr_sizes = [int(round(q1)), int(round(median)), int(round(q3))]
            weekly_prs[week] = pr_stats
    return dict(sorted(weekly.items())), dict(sorted(weekly_prs.items()))


def infer_repo_label_from_metrics_csv(input_path: Path) -> str:
    suffix = "_weekly_report_data"
    stem = input_path.stem
    return stem[: -len(suffix)] if stem.endswith(suffix) else stem


def format_compact_number(value: int) -> str:
    if value >= 1_000_000:
        text = f"{value / 1_000_000:.1f}M"
    elif value >= 1_000:
        text = f"{value / 1_000:.1f}K"
    else:
        text = str(value)
    return text.replace(".0", "")


def to_title_case(text: str) -> str:
    return text.title()


def axis_number_formatter(value: float, _position: int) -> str:
    return format_compact_number(int(round(value)))


def render_three_panel_plot(
    df: pd.DataFrame,
    output_path: Path,
    *,
    figure_title: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid", context="notebook")

    fig, axes = plt.subplots(3, 1, figsize=(13.5, 10.0), sharex=True)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.90, bottom=0.10, hspace=0.34)
    fig.suptitle(figure_title, fontsize=18, fontweight="bold", x=0.5, y=0.965, ha="center")

    specs = [
        {
            "column": "significant_lines_changed",
            "label": "Significant lines changed per week",
            "color": "#1d4ed8",
            "legend_labels": ["Lines changed"],
        },
        {
            "column": "prs",
            "label": "Merged PRs per week",
            "color": "#7c3aed",
            "legend_labels": ["PRs per week"],
        },
        {
            "column": "median_pr_size",
            "label": "Median PR size with IQR by week",
            "color": "#d97706",
            "legend_labels": ["Median PR size", "IQR"],
            "ribbon_low": "q1_pr_size",
            "ribbon_high": "q3_pr_size",
        },
    ]

    for index, (ax, spec) in enumerate(zip(axes, specs)):
        plot_df = df.dropna(subset=[spec["column"]]).copy()
        sns.lineplot(
            data=plot_df,
            x="week_start",
            y=spec["column"],
            ax=ax,
            color=spec["color"],
            linewidth=2.25,
        )
        if spec.get("ribbon_low") and spec.get("ribbon_high"):
            ribbon_df = df.dropna(subset=[spec["ribbon_low"], spec["ribbon_high"]]).copy()
            ax.fill_between(
                ribbon_df["week_start"],
                ribbon_df[spec["ribbon_low"]],
                ribbon_df[spec["ribbon_high"]],
                color=spec["color"],
                alpha=0.18,
            )
        else:
            ax.fill_between(plot_df["week_start"], plot_df[spec["column"]], color=spec["color"], alpha=0.16)
        ax.set_title(spec["label"], loc="left", fontsize=13, fontweight="semibold", pad=10)
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.yaxis.set_major_formatter(FuncFormatter(axis_number_formatter))
        ax.grid(True, axis="y", color="#d7dee7", linewidth=0.8)
        ax.grid(False, axis="x")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#cbd5e1")
        ax.spines["bottom"].set_color("#cbd5e1")
        ax.margins(x=0.01)
        if index < 2:
            ax.tick_params(axis="x", labelbottom=False)

        legend_handles: list[object] = [Line2D([0], [0], color=spec["color"], lw=2.25)]
        if len(spec["legend_labels"]) > 1:
            legend_handles.append(Patch(facecolor=spec["color"], alpha=0.18, edgecolor="none"))
        ax.legend(
            legend_handles,
            spec["legend_labels"],
            loc="upper left",
            frameon=False,
            fontsize=10,
            handlelength=2.8,
        )

    axes[2].xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    axes[2].tick_params(axis="x", pad=8)
    plt.setp(axes[2].get_xticklabels(), rotation=0, ha="center")

    events = [
        (pd.Timestamp("2025-12-18"), "GPT-5.2-Codex", "#64748b"),
        (pd.Timestamp("2026-02-02"), "Codex app +\nGPT-5.3-Codex", "#059669"),
    ]
    for ax in axes:
        for dt, _label, color in events:
            ax.axvline(x=dt, color=color, linestyle="--", linewidth=1.0, alpha=0.6, zorder=0)
    y_top = axes[0].get_ylim()[1]
    for dt, label, color in events:
        axes[0].annotate(
            label,
            xy=(dt, y_top),
            xytext=(0, -3),
            textcoords="offset points",
            fontsize=7.5, color=color, ha="center", va="top",
            annotation_clip=True,
            bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85),
        )

    fig.text(
        0.08, 0.015,
        "Lines changed = additions + deletions from git log --numstat -w (whitespace-only excluded)  ·  "
        "PR size = added + deleted lines per commit with (#PR) in subject, analysed on main --first-parent",
        fontsize=8.5, color="#64748b", ha="left", va="bottom",
    )

    fig.savefig(output_path, format=output_path.suffix.lstrip("."), dpi=160)
    plt.close(fig)


def build_svg(
    weekly: dict[date, WeeklyStats],
    weekly_prs: dict[date, WeeklyPrStats],
    output_path: Path,
    repo_label: str,
) -> None:
    df = pd.DataFrame(
        [
            {
                "week_start": pd.Timestamp(week),
                "significant_lines_changed": stats.significant_lines_changed,
                "prs": weekly_prs[week].prs,
                "median_pr_size": weekly_prs[week].median_size if weekly_prs[week].prs else None,
                "q1_pr_size": weekly_prs[week].q1_size if weekly_prs[week].prs else None,
                "q3_pr_size": weekly_prs[week].q3_size if weekly_prs[week].prs else None,
            }
            for week, stats in weekly.items()
        ]
    )
    render_three_panel_plot(
        df,
        output_path,
        figure_title=f"{to_title_case(repo_label)} Weekly Engineering Activity",
    )


def summarize(weekly: dict[date, WeeklyStats]) -> str:
    total_commits = sum(stats.commits for stats in weekly.values())
    total_changes = sum(stats.significant_lines_changed for stats in weekly.values())
    busiest_commit_week, busiest_commit_stats = max(
        weekly.items(),
        key=lambda item: item[1].commits,
    )
    busiest_change_week, busiest_change_stats = max(
        weekly.items(),
        key=lambda item: item[1].significant_lines_changed,
    )
    return "\n".join(
        [
            f"Weeks analyzed: {len(weekly)}",
            f"Total commits: {total_commits}",
            f"Total significant lines changed: {total_changes}",
            f"Busiest commit week: {busiest_commit_week} ({busiest_commit_stats.commits} commits)",
            (
                "Largest line-change week: "
                f"{busiest_change_week} ({busiest_change_stats.significant_lines_changed} lines)"
            ),
        ]
    )


def summarize_prs(weekly: dict[date, WeeklyPrStats], rev_spec: str) -> str:
    total_prs = sum(stats.prs for stats in weekly.values())
    total_size = sum(stats.total_size for stats in weekly.values())
    busiest_week, busiest_stats = max(weekly.items(), key=lambda item: item[1].prs)
    largest_avg_week, largest_avg_stats = max(weekly.items(), key=lambda item: item[1].average_size)
    average_pr_size = round(total_size / total_prs) if total_prs else 0
    return "\n".join(
        [
            f"PR weeks analyzed: {len(weekly)}",
            f"PR rev-spec: {rev_spec}",
            f"Total merged PRs detected: {total_prs}",
            f"Average PR size: {average_pr_size} lines",
            f"Busiest PR week: {busiest_week} ({busiest_stats.prs} PRs)",
            f"Largest average PR week: {largest_avg_week} ({round(largest_avg_stats.average_size)} lines)",
        ]
    )


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    repo = Path(args.repo).resolve()

    if args.main_chart_only:
        if not args.metrics_csv_input:
            print("--main-chart-only requires --metrics-csv-input", file=sys.stderr)
            return 1
        metrics_csv_input = Path(args.metrics_csv_input).resolve()
        weekly, weekly_prs = read_metrics_csv(metrics_csv_input)
        if not weekly:
            print(f"No weekly rows found in CSV: {metrics_csv_input}", file=sys.stderr)
            return 1
        repo_label = args.repo_label or infer_repo_label_from_metrics_csv(metrics_csv_input)
        svg_path = output_dir / f"{repo_label}_weekly_metrics.svg"
        build_svg(weekly, weekly_prs, svg_path, repo_label)
        print(summarize(weekly))
        print(summarize_prs(weekly_prs, "from-csv"))
        print(f"CSV: {metrics_csv_input}")
        print(f"SVG: {svg_path}")
        return 0

    if not (repo / ".git").exists():
        print(f"Repository path does not look like a git checkout: {repo}", file=sys.stderr)
        return 1

    weekly = collect_weekly_stats(repo, args.rev_spec)
    if not weekly:
        print("No commits found to analyze.", file=sys.stderr)
        return 1

    repo_name = args.repo_label or repo.name
    csv_path = output_dir / f"{repo_name}_weekly_report_data.csv"
    svg_path = output_dir / f"{repo_name}_weekly_metrics.svg"

    pr_rev_spec = get_default_pr_rev_spec(repo)
    if args.metrics_csv_input:
        _, weekly_prs = read_metrics_csv(Path(args.metrics_csv_input).resolve())
        weekly_prs = fill_missing_pr_weeks(weekly_prs, list(weekly.keys()))
    else:
        weekly_prs = fill_missing_pr_weeks(collect_weekly_pr_stats(repo, pr_rev_spec), list(weekly.keys()))

    write_csv(weekly, weekly_prs, csv_path)
    build_svg(weekly, weekly_prs, svg_path, repo_name)

    print(summarize(weekly))
    if weekly_prs:
        print(summarize_prs(weekly_prs, pr_rev_spec if not args.metrics_csv_input else "from-csv"))
    print(f"CSV: {csv_path}")
    print(f"SVG: {svg_path}")
    return 0
