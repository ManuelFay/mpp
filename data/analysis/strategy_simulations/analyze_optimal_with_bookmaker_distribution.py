#!/usr/bin/env python3
"""Assess computed-optimal picks with bookmaker-injected score probabilities."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bookmaker_injected_strategy


DEFAULT_COMPLETED_FILE = "data/mpg/completed_games.csv"
DEFAULT_ODDS_LOG = "data/bookmaker_injected/bookmaker_score_odds.csv"
DEFAULT_PREDICTION_LOG = "data/bookmaker_injected/expected_mpg_top5.csv"
DEFAULT_SNAPSHOT_DIR = "data/mpg/strategy_snapshots"
DEFAULT_OUT_DIR = "data/analysis/strategy_simulations/optimal_bookmaker_injected_assessment"
DEFAULT_ROLLOUTS = 200_000
DEFAULT_SEED = 20260624

RESULT_FIELDS = [
    "commence_time",
    "match",
    "strategy_snapshot",
    "selected_score",
    "actual_score",
    "outcome_correct",
    "exact_score_correct",
    "selected_base_points",
    "base_points",
    "exact_bonus_points",
    "realized_points",
    "bookmaker_outcome_probability",
    "bookmaker_exact_score_probability",
    "bookmaker_conditional_bettor_share",
    "bookmaker_nominal_bonus_label",
    "bookmaker_nominal_bonus_points",
    "bookmaker_expected_bonus_points",
    "bookmaker_assessed_expected_points",
    "original_compute_expected_points",
]

SUMMARY_FIELDS = [
    "completed_picks",
    "realized_points",
    "bookmaker_assessed_expected_points",
    "original_compute_expected_points",
    "realized_minus_bookmaker_ev",
    "simulated_mean",
    "simulated_sd",
    "realized_percentile",
    "p10",
    "median",
    "p90",
]


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def normalize_team(team: str) -> str:
    return bookmaker_injected_strategy.normalize_team(team)


def match_key(home_team: str, away_team: str) -> tuple[str, str]:
    return (normalize_team(home_team), normalize_team(away_team))


def parse_utc(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def snapshot_time(path: Path) -> dt.datetime:
    stamp = path.name.removeprefix("mpg_optimal_strategy_").removesuffix(".csv")
    return dt.datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)


def load_strategy_rows(snapshot_dir: str | Path) -> dict[tuple[str, str], list[dict[str, str]]]:
    rows_by_match: dict[tuple[str, str], list[dict[str, str]]] = {}
    for path in sorted(Path(snapshot_dir).glob("**/mpg_optimal_strategy_*.csv")):
        captured_at = snapshot_time(path)
        for row in read_csv(path):
            key = match_key(row["matched_home_team"], row["matched_away_team"])
            rows_by_match.setdefault(key, []).append(
                {
                    **row,
                    "snapshot_path": str(path),
                    "snapshot_captured_at": captured_at.isoformat(),
                }
            )
    for rows in rows_by_match.values():
        rows.sort(key=lambda row: parse_utc(row["snapshot_captured_at"]))
    return rows_by_match


def select_strategy_row(
    rows: list[dict[str, str]],
    commence_time: str,
) -> dict[str, str]:
    kickoff = parse_utc(commence_time)
    pre_kickoff = [
        row for row in rows if parse_utc(row["snapshot_captured_at"]) < kickoff
    ]
    # Early historical snapshots were captured after some games had kicked off.
    # Use the earliest available row for those games rather than dropping them.
    return pre_kickoff[-1] if pre_kickoff else rows[0]


def latest_rows_by_submission(rows: list[dict[str, str]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        key = (
            normalize_team(row["home_team"]),
            normalize_team(row["away_team"]),
            row["submission_id"],
        )
        grouped.setdefault(key, []).append(row)

    latest: dict[tuple[str, str], tuple[dt.datetime, list[dict[str, str]]]] = {}
    for (home, away, _submission), submission_rows in grouped.items():
        logged_at = parse_utc(submission_rows[0]["logged_at_utc"])
        key = (home, away)
        if key not in latest or logged_at > latest[key][0]:
            latest[key] = (logged_at, submission_rows)
    return {key: value[1] for key, value in latest.items()}


def latest_prediction_metadata(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, object]]:
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        match = row["match"]
        if " vs " not in match:
            continue
        home_team, away_team = match.split(" vs ", maxsplit=1)
        home, away = match_key(home_team, away_team)
        grouped.setdefault((home, away, row["submission_id"]), []).append(row)

    latest: dict[tuple[str, str], tuple[dt.datetime, list[dict[str, str]]]] = {}
    for (home, away, _submission), submission_rows in grouped.items():
        logged_at = parse_utc(submission_rows[0]["logged_at_utc"])
        key = (home, away)
        if key not in latest or logged_at > latest[key][0]:
            latest[key] = (logged_at, submission_rows)

    result: dict[tuple[str, str], dict[str, object]] = {}
    for key, (_logged_at, submission_rows) in latest.items():
        row = submission_rows[0]
        result[key] = {
            "sigma": float(row["conditional_share_sigma"]),
            "outcome_probabilities": {
                "home": 0.0,
                "draw": 0.0,
                "away": 0.0,
            },
            "outcome_points": {
                "home": 0.0,
                "draw": 0.0,
                "away": 0.0,
            },
        }
        for submission_row in submission_rows:
            outcome = submission_row["outcome"]
            result[key]["outcome_probabilities"][outcome] = float(submission_row["outcome_probability"])  # type: ignore[index]
            base_ev = float(submission_row["base_ev"])
            outcome_probability = float(submission_row["outcome_probability"])
            if outcome_probability > 0:
                result[key]["outcome_points"][outcome] = base_ev / outcome_probability  # type: ignore[index]
    return result


def score_outcome(score: str) -> str:
    home_goals, away_goals = (int(value) for value in score.split("-"))
    return bookmaker_injected_strategy.score_outcome(home_goals, away_goals)


def scored_rows(args: argparse.Namespace) -> list[dict[str, object]]:
    completed_rows = read_csv(args.completed_file)
    strategy_rows = load_strategy_rows(args.snapshot_dir)
    odds_rows = latest_rows_by_submission(read_csv(args.odds_log))
    metadata = latest_prediction_metadata(read_csv(args.prediction_log))

    results: list[dict[str, object]] = []
    for completed in sorted(completed_rows, key=lambda row: row["commence_time"]):
        key = match_key(completed["home_team"], completed["away_team"])
        if key not in strategy_rows or key not in odds_rows or key not in metadata:
            continue
        strategy = select_strategy_row(strategy_rows[key], completed["commence_time"])
        meta = metadata[key]
        ranked = bookmaker_injected_strategy.rank_scores(
            odds_rows[key],
            meta["outcome_probabilities"],  # type: ignore[arg-type]
            meta["outcome_points"],  # type: ignore[arg-type]
            completed["home_team"],
            completed["away_team"],
            float(meta["sigma"]),
        )
        selected_score = strategy["optimal_exact_score"]
        assessed = next((row for row in ranked if row.score == selected_score), None)
        if assessed is None:
            raise ValueError(
                f"Selected score {selected_score} missing from bookmaker odds for "
                f"{completed['home_team']} vs {completed['away_team']}"
            )

        actual_score = completed["final_score"]
        outcome_correct = assessed.outcome == score_outcome(actual_score)
        exact_score_correct = selected_score == actual_score
        selected_base_points = (
            assessed.base_ev / assessed.outcome_probability
            if assessed.outcome_probability
            else 0.0
        )
        realized_points = selected_base_points if outcome_correct else 0.0
        exact_bonus_points = assessed.bonus.nominal_points if exact_score_correct else 0.0
        if exact_score_correct:
            realized_points += exact_bonus_points

        results.append(
            {
                "commence_time": completed["commence_time"],
                "match": f"{completed['home_team']} vs {completed['away_team']}",
                "strategy_snapshot": strategy["snapshot_path"],
                "selected_score": selected_score,
                "actual_score": actual_score,
                "outcome_correct": outcome_correct,
                "exact_score_correct": exact_score_correct,
                "selected_base_points": selected_base_points,
                "base_points": selected_base_points if outcome_correct else 0.0,
                "exact_bonus_points": exact_bonus_points,
                "realized_points": realized_points,
                "bookmaker_outcome_probability": assessed.outcome_probability,
                "bookmaker_exact_score_probability": assessed.score_probability,
                "bookmaker_conditional_bettor_share": assessed.conditional_bettor_share,
                "bookmaker_nominal_bonus_label": assessed.bonus.nominal_label,
                "bookmaker_nominal_bonus_points": assessed.bonus.nominal_points,
                "bookmaker_expected_bonus_points": assessed.bonus.expected_points,
                "bookmaker_assessed_expected_points": assessed.total_ev,
                "original_compute_expected_points": float(strategy["optimal_expected_points"]),
            }
        )
    return results


def sample_bonus_points(
    share: float,
    sigma: float,
    count: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if sigma <= 0:
        label, points = bookmaker_injected_strategy.nominal_bonus(share)
        return np.full(count, points)
    shares = rng.normal(share, sigma, size=count)
    return np.select(
        [shares > 0.30, shares >= 0.20, shares >= 0.05, shares >= 0.005],
        [20.0, 30.0, 50.0, 70.0],
        default=100.0,
    )


def simulate_totals(rows: list[dict[str, object]], rollouts: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    totals = np.zeros(rollouts)
    for row in rows:
        outcome_probability = float(row["bookmaker_outcome_probability"])
        exact_probability = float(row["bookmaker_exact_score_probability"])
        base_points = float(row["selected_base_points"])
        draws = rng.random(rollouts)
        exact = draws < exact_probability
        outcome_only = (draws >= exact_probability) & (draws < outcome_probability)
        totals[outcome_only] += base_points
        exact_count = int(exact.sum())
        if exact_count:
            totals[exact] += base_points + sample_bonus_points(
                float(row["bookmaker_conditional_bettor_share"]),
                0.01,
                exact_count,
                rng,
            )
    return totals


def write_plot(path: Path, totals: np.ndarray, realized: float) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpp-matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mean = float(totals.mean())
    sigma = float(totals.std())
    percentile = float(np.mean(totals <= realized))

    fig, (box_ax, hist_ax) = plt.subplots(
        2, 1, figsize=(11, 7), gridspec_kw={"height_ratios": [1, 3]}
    )
    box_ax.boxplot(totals, vert=False, widths=0.5, showfliers=False)
    box_ax.scatter([realized], [1], marker="D", s=80, color="#c62828", zorder=5)
    box_ax.axvline(mean, color="#e66101", linewidth=2)
    box_ax.set_yticks([])
    box_ax.set_title("Compute-optimal picks assessed with bookmaker-injected distribution")

    hist_ax.hist(totals, bins=70, density=True, color="#9ecae1", edgecolor="white")
    hist_ax.axvline(mean, color="#e66101", linewidth=2, label=f"Mean: {mean:.1f}")
    hist_ax.axvline(realized, color="#c62828", linewidth=2.5, label=f"Realized: {realized:.0f}")
    for multiple, color in ((1, "#e6ab02"), (2, "#7570b3")):
        hist_ax.axvline(mean - multiple * sigma, color=color, linestyle="--", linewidth=1.5)
        hist_ax.axvline(mean + multiple * sigma, color=color, linestyle="--", linewidth=1.5)
    hist_ax.annotate(
        f"{percentile:.1%} percentile",
        xy=(realized, hist_ax.get_ylim()[1] * 0.75),
        xytext=(12, 0),
        textcoords="offset points",
        color="#c62828",
        fontweight="bold",
    )
    hist_ax.set_xlabel("Total points over resolved games")
    hist_ax.set_ylabel("Simulated density")
    hist_ax.legend(frameon=False)
    hist_ax.grid(axis="y", color="#e5e7eb", linewidth=0.8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--completed-file", default=DEFAULT_COMPLETED_FILE)
    parser.add_argument("--odds-log", default=DEFAULT_ODDS_LOG)
    parser.add_argument("--prediction-log", default=DEFAULT_PREDICTION_LOG)
    parser.add_argument("--snapshot-dir", default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--rollouts", type=int, default=DEFAULT_ROLLOUTS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--write-rollouts", action="store_true")
    parser.add_argument("--write-plot", action="store_true")
    args = parser.parse_args()

    rows = scored_rows(args)
    if not rows:
        raise SystemExit("No resolved games had both compute strategy and bookmaker-injected odds")

    totals = simulate_totals(rows, args.rollouts, args.seed)
    realized = sum(float(row["realized_points"]) for row in rows)
    expected = sum(float(row["bookmaker_assessed_expected_points"]) for row in rows)
    original_expected = sum(float(row["original_compute_expected_points"]) for row in rows)
    summary = {
        "completed_picks": len(rows),
        "realized_points": realized,
        "bookmaker_assessed_expected_points": expected,
        "original_compute_expected_points": original_expected,
        "realized_minus_bookmaker_ev": realized - expected,
        "simulated_mean": float(totals.mean()),
        "simulated_sd": float(totals.std()),
        "realized_percentile": float(np.mean(totals <= realized)),
        "p10": float(np.quantile(totals, 0.10)),
        "median": float(np.quantile(totals, 0.50)),
        "p90": float(np.quantile(totals, 0.90)),
    }

    out_dir = Path(args.out_dir)
    write_csv(out_dir / "optimal_assessed_with_bookmaker_injected_results.csv", rows, RESULT_FIELDS)
    write_csv(out_dir / "optimal_assessed_with_bookmaker_injected_summary.csv", [summary], SUMMARY_FIELDS)
    if args.write_rollouts:
        write_csv(
            out_dir / "optimal_assessed_with_bookmaker_injected_rollouts.csv",
            [
                {"rollout": index + 1, "total_points": float(total)}
                for index, total in enumerate(totals)
            ],
            ["rollout", "total_points"],
        )
    if args.write_plot:
        write_plot(out_dir / "optimal_assessed_with_bookmaker_injected_distribution.png", totals, realized)

    print(f"Completed compute-optimal picks assessed: {len(rows)}")
    print(f"Realized points: {realized:.2f}")
    print(f"Bookmaker-assessed EV: {expected:.2f}")
    print(f"Original compute EV: {original_expected:.2f}")
    print(f"Realized minus bookmaker EV: {realized - expected:+.2f}")
    print(f"Simulated mean / standard deviation: {float(totals.mean()):.2f} / {float(totals.std()):.2f}")
    print(f"Realized percentile: {float(np.mean(totals <= realized)):.2%}")
    print(f"Saved summary: {out_dir / 'optimal_assessed_with_bookmaker_injected_summary.csv'}")
    print(f"Saved per-game results: {out_dir / 'optimal_assessed_with_bookmaker_injected_results.csv'}")
    if args.write_rollouts:
        print(f"Saved rollouts: {out_dir / 'optimal_assessed_with_bookmaker_injected_rollouts.csv'}")
    if args.write_plot:
        print(f"Saved plot: {out_dir / 'optimal_assessed_with_bookmaker_injected_distribution.png'}")


if __name__ == "__main__":
    main()
