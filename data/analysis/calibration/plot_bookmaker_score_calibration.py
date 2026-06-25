#!/usr/bin/env python3
"""Plot bookmaker-injected outcome and exact-score calibration on resolved games."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import os
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bookmaker_injected_strategy


DEFAULT_ODDS_FILE = ROOT / "data/bookmaker_injected/bookmaker_score_odds.csv"
DEFAULT_COMPLETED_FILE = ROOT / "data/mpg/completed_games.csv"
DEFAULT_OUT_DIR = ROOT / "data/analysis/calibration"
DEFAULT_PLOT = DEFAULT_OUT_DIR / "bookmaker_score_probability_calibration.png"
DEFAULT_OUTCOME_CSV = DEFAULT_OUT_DIR / "bookmaker_score_outcome_calibration.csv"
DEFAULT_EXACT_CSV = DEFAULT_OUT_DIR / "bookmaker_score_exact_calibration.csv"
DEFAULT_OUTCOME_RECORDS = DEFAULT_OUT_DIR / "bookmaker_score_outcome_calibration_records.csv"
DEFAULT_EXACT_RECORDS = DEFAULT_OUT_DIR / "bookmaker_score_exact_calibration_records.csv"


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_csv(path: str | Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def normalize_team(team: str) -> str:
    return bookmaker_injected_strategy.normalize_team(team)


def parse_utc(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def outcome(home_goals: int, away_goals: int) -> str:
    return bookmaker_injected_strategy.score_outcome(home_goals, away_goals)


def group_odds_submissions(
    rows: list[dict[str, str]],
) -> dict[tuple[str, str], list[tuple[dt.datetime, str, list[dict[str, str]]]]]:
    by_submission: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_submission[row["submission_id"]].append(row)

    grouped: dict[tuple[str, str], list[tuple[dt.datetime, str, list[dict[str, str]]]]] = defaultdict(list)
    for submission_id, submission_rows in by_submission.items():
        first = submission_rows[0]
        key = (normalize_team(first["home_team"]), normalize_team(first["away_team"]))
        grouped[key].append((parse_utc(first["logged_at_utc"]), submission_id, submission_rows))

    for submissions in grouped.values():
        submissions.sort(key=lambda item: item[0])
    return grouped


def latest_pre_kickoff_submission(
    submissions: list[tuple[dt.datetime, str, list[dict[str, str]]]],
    commence_time: str,
) -> tuple[dt.datetime, str, list[dict[str, str]]] | None:
    kickoff = parse_utc(commence_time)
    valid = [submission for submission in submissions if submission[0] < kickoff]
    return valid[-1] if valid else None


def wilson_interval(hits: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = hits / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def bin_records(
    records: list[dict[str, object]],
    probability_field: str,
    hit_field: str,
    bins: list[tuple[float, float]],
) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for low, high in bins:
        in_bin = [
            row
            for row in records
            if low <= float(row[probability_field]) < high
            or (high == 1.0 and low <= float(row[probability_field]) <= high)
        ]
        if not in_bin:
            continue
        n = len(in_bin)
        hits = sum(int(row[hit_field]) for row in in_bin)
        avg_predicted = sum(float(row[probability_field]) for row in in_bin) / n
        observed = hits / n
        wilson_low, wilson_high = wilson_interval(hits, n)
        summaries.append(
            {
                "bin": f"{low:.2f}-{high:.2f}",
                "bin_low": low,
                "bin_high": high,
                "n": n,
                "hits": hits,
                "avg_predicted_probability": avg_predicted,
                "observed_hit_rate": observed,
                "wilson_low": wilson_low,
                "wilson_high": wilson_high,
            }
        )
    return summaries


def build_records(
    odds_rows: list[dict[str, str]],
    completed_rows: list[dict[str, str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    submissions_by_match = group_odds_submissions(odds_rows)
    outcome_records: list[dict[str, object]] = []
    exact_records: list[dict[str, object]] = []

    for completed in sorted(completed_rows, key=lambda row: row["commence_time"]):
        key = (normalize_team(completed["home_team"]), normalize_team(completed["away_team"]))
        submission = latest_pre_kickoff_submission(
            submissions_by_match.get(key, []),
            completed["commence_time"],
        )
        if submission is None:
            continue

        logged_at, submission_id, rows = submission
        actual_home = int(completed["home_score"])
        actual_away = int(completed["away_score"])
        actual_score = f"{actual_home}-{actual_away}"
        actual_outcome = outcome(actual_home, actual_away)
        raw_total = sum(1.0 / float(row["odds_decimal"]) for row in rows)
        if raw_total <= 0:
            continue

        outcome_probabilities = {"home": 0.0, "draw": 0.0, "away": 0.0}
        exact_rows = [row for row in rows if row["score"].strip().lower() != "other"]
        for row in exact_rows:
            predicted = (1.0 / float(row["odds_decimal"])) / raw_total
            row_outcome = outcome(int(row["home_goals"]), int(row["away_goals"]))
            outcome_probabilities[row_outcome] += predicted
            exact_records.append(
                {
                    "match": completed["home_team"] + " vs " + completed["away_team"],
                    "commence_time": completed["commence_time"],
                    "logged_at_utc": logged_at.isoformat(),
                    "submission_id": submission_id,
                    "score": row["score"],
                    "actual_score": actual_score,
                    "predicted_probability": predicted,
                    "hit": int(row["score"] == actual_score),
                }
            )

        for row_outcome, predicted in outcome_probabilities.items():
            outcome_records.append(
                {
                    "match": completed["home_team"] + " vs " + completed["away_team"],
                    "commence_time": completed["commence_time"],
                    "logged_at_utc": logged_at.isoformat(),
                    "submission_id": submission_id,
                    "outcome": row_outcome,
                    "actual_outcome": actual_outcome,
                    "predicted_probability": predicted,
                    "hit": int(row_outcome == actual_outcome),
                }
            )

    return outcome_records, exact_records


def plot_calibration(
    path: str | Path,
    outcome_bins: list[dict[str, object]],
    exact_bins: list[dict[str, object]],
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpp-matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    panels = [
        (axes[0], outcome_bins, "Outcome probabilities", "#1f77b4", 100),
        (axes[1], exact_bins, "Exact-score probabilities", "#2ca02c", 20),
    ]
    for ax, rows, title, color, axis_max in panels:
        xs = [100 * float(row["avg_predicted_probability"]) for row in rows]
        ys = [100 * float(row["observed_hit_rate"]) for row in rows]
        yerr = [
            [100 * (float(row["observed_hit_rate"]) - float(row["wilson_low"])) for row in rows],
            [100 * (float(row["wilson_high"]) - float(row["observed_hit_rate"])) for row in rows],
        ]
        ax.plot([0, axis_max], [0, axis_max], color="#555555", linestyle="--", linewidth=1.5, label="Perfect calibration")
        ax.errorbar(
            xs,
            ys,
            yerr=yerr,
            marker="o",
            color=color,
            linewidth=2,
            capsize=4,
            label="Observed hit rate",
        )
        for index, (x, y, row) in enumerate(zip(xs, ys, rows)):
            offset = 8 if index % 2 == 0 else -20
            ax.annotate(
                f"n={row['n']}\n{row['hits']}/{row['n']}",
                xy=(x, y),
                xytext=(0, offset),
                textcoords="offset points",
                ha="center",
                fontsize=7,
                color="#333333",
            )
        ax.set_title(title)
        ax.set_xlabel("Average bookmaker-implied probability (%)")
        ax.set_xlim(0, axis_max)
        ax.set_ylim(0, axis_max)
        ax.grid(color="#dddddd", linewidth=0.8)
        ax.legend(loc="upper left")
    for ax in axes:
        ax.set_ylabel("Observed occurrence rate (%)")
    fig.suptitle("Bookmaker score-odds calibration on resolved logged games", fontsize=15)
    fig.text(
        0.01,
        0.01,
        "Uses latest pre-kickoff logged bookmaker_score_odds submission per resolved game; "
        "exact-score market includes Other in normalization but does not allocate Other to outcomes.",
        fontsize=9,
        color="#444444",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--odds-file", default=DEFAULT_ODDS_FILE)
    parser.add_argument("--completed-file", default=DEFAULT_COMPLETED_FILE)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    outcome_records, exact_records = build_records(
        read_csv(args.odds_file),
        read_csv(args.completed_file),
    )
    probability_bins = [(index / 10, (index + 1) / 10) for index in range(10)]
    exact_probability_bins = [
        (0.00, 0.01),
        (0.01, 0.02),
        (0.02, 0.03),
        (0.03, 0.04),
        (0.04, 0.05),
        (0.05, 0.075),
        (0.075, 0.10),
        (0.10, 0.15),
        (0.15, 0.20),
        (0.20, 1.00),
    ]
    outcome_bins = bin_records(outcome_records, "predicted_probability", "hit", probability_bins)
    exact_bins = bin_records(exact_records, "predicted_probability", "hit", exact_probability_bins)

    write_csv(
        out_dir / DEFAULT_OUTCOME_RECORDS.name,
        outcome_records,
        ["match", "commence_time", "logged_at_utc", "submission_id", "outcome", "actual_outcome", "predicted_probability", "hit"],
    )
    write_csv(
        out_dir / DEFAULT_EXACT_RECORDS.name,
        exact_records,
        ["match", "commence_time", "logged_at_utc", "submission_id", "score", "actual_score", "predicted_probability", "hit"],
    )
    summary_fields = [
        "bin",
        "bin_low",
        "bin_high",
        "n",
        "hits",
        "avg_predicted_probability",
        "observed_hit_rate",
        "wilson_low",
        "wilson_high",
    ]
    write_csv(out_dir / DEFAULT_OUTCOME_CSV.name, outcome_bins, summary_fields)
    write_csv(out_dir / DEFAULT_EXACT_CSV.name, exact_bins, summary_fields)
    plot_path = out_dir / DEFAULT_PLOT.name
    plot_calibration(plot_path, outcome_bins, exact_bins)

    resolved_games = len({row["match"] for row in outcome_records})
    print(f"Matched resolved games: {resolved_games}")
    print(f"Outcome records: {len(outcome_records)}")
    print(f"Exact-score records: {len(exact_records)}")
    print(f"Saved plot: {plot_path}")


if __name__ == "__main__":
    main()
