#!/usr/bin/env python3
"""Compare requested fixed-score MPG strategies on completed games."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import analyze_bookmaker_injected_results as bookmaker_results
import bookmaker_injected_strategy
import compute_mpg_strategy


DEFAULT_COMPLETED_FILE = "data/mpg/completed_games.csv"
DEFAULT_SCORE_EV_FILE = "data/mpg/mpg_score_expected_values.csv"
DEFAULT_OPTIMAL_FILE = "data/mpg/mpg_optimal_strategy.csv"
DEFAULT_PREDICTION_FILE = "data/bookmaker_injected/expected_mpg_top5.csv"
DEFAULT_MPG_FILE = "data/mpg/mpg.txt"
DEFAULT_OUT_DIR = "data/analysis/strategy_simulations/requested_strategies"
DEFAULT_ROLLOUTS = 200_000
DEFAULT_SEED = 20260616
DEFAULT_SNAPSHOT_DIR = "data/mpg/strategy_snapshots"

OUTCOMES = ("home", "draw", "away")

RESULT_FIELDS = [
    "strategy",
    "commence_time",
    "match",
    "selected_score",
    "actual_score",
    "outcome_correct",
    "exact_score_correct",
    "base_points",
    "exact_bonus_points",
    "realized_points",
    "expected_points",
    "realized_minus_expected",
]

SUMMARY_FIELDS = [
    "strategy",
    "completed_picks",
    "realized_points",
    "expected_points",
    "realized_minus_expected",
    "simulated_mean",
    "simulated_sd",
    "realized_percentile",
    "p10",
    "median",
    "p90",
    "zero_point_probability",
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


def normalized_team(team: str) -> str:
    return compute_mpg_strategy.normalize_team(
        bookmaker_injected_strategy.normalize_team(team)
    )


def score_outcome(score: str) -> str:
    home_goals, away_goals = (int(value) for value in score.split("-"))
    return compute_mpg_strategy.score_outcome(home_goals, away_goals)


def match_key(row: dict[str, str]) -> tuple[str, str]:
    return (normalized_team(row["home_team"]), normalized_team(row["away_team"]))


def score_ev_lookup(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], dict[str, str]]:
    return {
        (
            normalized_team(row["matched_home_team"]),
            normalized_team(row["matched_away_team"]),
            row["score"],
        ): row
        for row in rows
    }


def optimal_lookup(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {
        (
            normalized_team(row["matched_home_team"]),
            normalized_team(row["matched_away_team"]),
        ): row
        for row in rows
    }


def completed_keys(rows: list[dict[str, str]]) -> set[tuple[str, str]]:
    return {match_key(row) for row in rows}


def score_ev_keys(
    rows: list[dict[str, str]],
) -> set[tuple[str, str, str]]:
    return {
        (
            normalized_team(row["matched_home_team"]),
            normalized_team(row["matched_away_team"]),
            row["score"],
        )
        for row in rows
    }


def optimal_keys(rows: list[dict[str, str]]) -> set[tuple[str, str]]:
    return {
        (
            normalized_team(row["matched_home_team"]),
            normalized_team(row["matched_away_team"]),
        )
        for row in rows
    }


def missing_completed_keys(
    completed_rows: list[dict[str, str]],
    score_rows: list[dict[str, str]],
    optimal_rows: list[dict[str, str]],
) -> set[tuple[str, str]]:
    keys = completed_keys(completed_rows)
    score_match_keys = {(home, away) for home, away, _score in score_ev_keys(score_rows)}
    return keys - score_match_keys.intersection(optimal_keys(optimal_rows))


def required_score_keys(
    completed_rows: list[dict[str, str]],
    optimal_rows: list[dict[str, str]],
) -> set[tuple[str, str, str]]:
    optimal_by_key = {
        (
            normalized_team(row["matched_home_team"]),
            normalized_team(row["matched_away_team"]),
        ): row
        for row in optimal_rows
    }
    required: set[tuple[str, str, str]] = set()
    for completed in completed_rows:
        key = match_key(completed)
        required.update(
            {
                (*key, "0-0"),
                (*key, "1-1"),
                (*key, "1-0"),
                (*key, "0-1"),
            }
        )
        optimal = optimal_by_key.get(key)
        if optimal is not None:
            required.add((*key, optimal["optimal_exact_score"]))
    return required


def files_cover_completed_games(
    completed_rows: list[dict[str, str]],
    score_rows: list[dict[str, str]],
    optimal_rows: list[dict[str, str]],
) -> bool:
    if missing_completed_keys(completed_rows, score_rows, optimal_rows):
        return False
    return required_score_keys(completed_rows, optimal_rows) <= score_ev_keys(score_rows)


def snapshot_pairs(snapshot_dir: str | Path | None = None) -> list[tuple[Path, Path]]:
    root = Path(DEFAULT_SNAPSHOT_DIR if snapshot_dir is None else snapshot_dir)
    score_files = {
        path.name.removeprefix("mpg_score_expected_values_").removesuffix(".csv"): path
        for path in root.glob("**/mpg_score_expected_values_*.csv")
    }
    optimal_files = {
        path.name.removeprefix("mpg_optimal_strategy_").removesuffix(".csv"): path
        for path in root.glob("**/mpg_optimal_strategy_*.csv")
    }
    return [
        (score_files[stamp], optimal_files[stamp])
        for stamp in sorted(score_files.keys() & optimal_files.keys(), reverse=True)
    ]


def load_matching_strategy_files(
    completed_rows: list[dict[str, str]],
    score_path: str | Path,
    optimal_path: str | Path,
    allow_snapshot_fallback: bool,
) -> tuple[
    list[dict[str, str]],
    list[dict[str, str]],
    Path,
    Path,
    bool,
]:
    score_path = Path(score_path)
    optimal_path = Path(optimal_path)
    score_rows = read_csv(score_path)
    optimal_rows = read_csv(optimal_path)
    if files_cover_completed_games(completed_rows, score_rows, optimal_rows):
        return score_rows, optimal_rows, score_path, optimal_path, False

    if allow_snapshot_fallback:
        for candidate_score_path, candidate_optimal_path in snapshot_pairs():
            candidate_score_rows = read_csv(candidate_score_path)
            candidate_optimal_rows = read_csv(candidate_optimal_path)
            if files_cover_completed_games(
                completed_rows,
                candidate_score_rows,
                candidate_optimal_rows,
            ):
                return (
                    candidate_score_rows,
                    candidate_optimal_rows,
                    candidate_score_path,
                    candidate_optimal_path,
                    True,
                )

    missing_keys = sorted(
        missing_completed_keys(completed_rows, score_rows, optimal_rows)
    )
    missing_scores = sorted(
        required_score_keys(completed_rows, optimal_rows) - score_ev_keys(score_rows)
    )
    details = []
    if missing_keys:
        details.append(
            "missing games: "
            + ", ".join(f"{home} vs {away}" for home, away in missing_keys[:5])
        )
    if missing_scores:
        details.append(
            "missing score rows: "
            + ", ".join(
                f"{home} vs {away} {score}"
                for home, away, score in missing_scores[:5]
            )
        )
    detail = "; ".join(details) if details else "incomplete strategy inputs"
    raise ValueError(
        f"{score_path} and {optimal_path} do not cover completed games ({detail})"
    )


def fixed_score_for_strategy(
    strategy: str,
    completed: dict[str, str],
    score_rows: dict[tuple[str, str, str], dict[str, str]],
) -> str:
    if strategy == "always_0_0":
        return "0-0"
    if strategy == "always_1_1":
        return "1-1"

    key = match_key(completed)
    home_row = score_rows[(*key, "1-0")]
    away_row = score_rows[(*key, "0-1")]
    home_probability = float(home_row["outcome_probability"])
    away_probability = float(away_row["outcome_probability"])
    if strategy == "underdog_1_0":
        return "1-0" if home_probability < away_probability else "0-1"
    if strategy == "favorite_1_0":
        return "1-0" if home_probability >= away_probability else "0-1"
    raise ValueError(f"Unknown fixed strategy {strategy}")


def pick_from_score_ev(
    strategy: str,
    completed: dict[str, str],
    score: str,
    score_rows: dict[tuple[str, str, str], dict[str, str]],
) -> bookmaker_results.ScoredPick:
    key = match_key(completed)
    row = score_rows.get((*key, score))
    if row is None:
        raise ValueError(f"Score {score} missing for {completed['home_team']} vs {completed['away_team']}")

    actual_score = completed["final_score"]
    actual_outcome = score_outcome(actual_score)
    selected_outcome = row["outcome"]
    outcome_correct = selected_outcome == actual_outcome
    exact_score_correct = score == actual_score
    exact_bonus_points = float(row["exact_bonus_points"]) if exact_score_correct else 0.0
    base_points = float(row["outcome_points"])
    realized_points = base_points + exact_bonus_points if outcome_correct else 0.0
    return bookmaker_results.ScoredPick(
        match=f"{completed['home_team']} vs {completed['away_team']}",
        commence_time=completed["commence_time"],
        selected_score=score,
        actual_score=actual_score,
        outcome_probability=float(row["outcome_probability"]),
        exact_score_probability=float(row["score_probability"]),
        conditional_bettor_share=float(row["score_conditional_probability"]),
        conditional_share_sigma=0.0,
        base_points=base_points,
        expected_points=float(row["total_expected_points"]),
        outcome_correct=outcome_correct,
        exact_score_correct=exact_score_correct,
        exact_bonus_points=exact_bonus_points,
        realized_points=realized_points,
    )


def fixed_strategy_picks(
    strategy: str,
    completed_rows: list[dict[str, str]],
    score_rows: dict[tuple[str, str, str], dict[str, str]],
) -> list[bookmaker_results.ScoredPick]:
    picks = []
    for completed in completed_rows:
        score = fixed_score_for_strategy(strategy, completed, score_rows)
        picks.append(pick_from_score_ev(strategy, completed, score, score_rows))
    return picks


def optimal_strategy_picks(
    completed_rows: list[dict[str, str]],
    score_rows: dict[tuple[str, str, str], dict[str, str]],
    optimal_rows: dict[tuple[str, str], dict[str, str]],
) -> list[bookmaker_results.ScoredPick]:
    picks = []
    for completed in completed_rows:
        optimal = optimal_rows[match_key(completed)]
        picks.append(
            pick_from_score_ev(
                "optimal_current",
                completed,
                optimal["optimal_exact_score"],
                score_rows,
            )
        )
    return picks


def bookmaker_picks(
    prediction_file: str,
    completed_file: str,
    mpg_file: str,
) -> list[bookmaker_results.ScoredPick]:
    return bookmaker_results.score_completed_picks(
        read_csv(prediction_file),
        read_csv(completed_file),
        read_csv(mpg_file),
    )


def summary_row(
    strategy: str,
    picks: list[bookmaker_results.ScoredPick],
    totals: np.ndarray,
) -> dict[str, object]:
    realized = sum(pick.realized_points for pick in picks)
    expected = sum(pick.expected_points for pick in picks)
    return {
        "strategy": strategy,
        "completed_picks": len(picks),
        "realized_points": realized,
        "expected_points": expected,
        "realized_minus_expected": realized - expected,
        "simulated_mean": float(totals.mean()),
        "simulated_sd": float(totals.std()),
        "realized_percentile": float(np.mean(totals <= realized)),
        "p10": float(np.quantile(totals, 0.10)),
        "median": float(np.quantile(totals, 0.50)),
        "p90": float(np.quantile(totals, 0.90)),
        "zero_point_probability": float(np.mean(totals == 0)),
    }


def result_rows(
    strategy: str, picks: list[bookmaker_results.ScoredPick]
) -> list[dict[str, object]]:
    rows = []
    for row in bookmaker_results.result_rows(picks):
        rows.append({"strategy": strategy, **row})
    return rows


def plot_results(
    path: Path,
    summaries: list[dict[str, object]],
    rollups: dict[str, np.ndarray],
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpp-matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ordered = [str(row["strategy"]) for row in summaries]
    colors = {
        "always_0_0": "#577590",
        "always_1_1": "#43aa8b",
        "underdog_1_0": "#f9c74f",
        "favorite_1_0": "#f3722c",
        "bookmaker_injected_top1": "#9b5de5",
        "optimal_current": "#277da1",
    }
    fig, (hist_ax, bar_ax) = plt.subplots(2, 1, figsize=(12, 9))

    for strategy in ordered:
        totals = rollups[strategy]
        hist_ax.hist(
            totals,
            bins=80,
            density=True,
            histtype="step",
            linewidth=1.8,
            color=colors.get(strategy),
            label=strategy,
        )
    hist_ax.set_title("Simulated total-points distributions on completed games")
    hist_ax.set_xlabel("Total points")
    hist_ax.set_ylabel("Density")
    hist_ax.grid(axis="y", color="#e5e7eb", linewidth=0.8)
    hist_ax.legend(frameon=False, fontsize=8)
    hist_ax.spines[["top", "right"]].set_visible(False)

    x = np.arange(len(ordered))
    realized = [float(row["realized_points"]) for row in summaries]
    expected = [float(row["expected_points"]) for row in summaries]
    width = 0.38
    bar_ax.bar(x - width / 2, realized, width, label="Realized", color="#264653")
    bar_ax.bar(x + width / 2, expected, width, label="Expected", color="#e76f51")
    bar_ax.set_title("Points gained in practice vs expected points")
    bar_ax.set_ylabel("Points")
    bar_ax.set_xticks(x, ordered, rotation=25, ha="right")
    bar_ax.grid(axis="y", color="#e5e7eb", linewidth=0.8)
    bar_ax.legend(frameon=False)
    bar_ax.spines[["top", "right"]].set_visible(False)

    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--completed-file", default=DEFAULT_COMPLETED_FILE)
    parser.add_argument("--score-ev-file", default=DEFAULT_SCORE_EV_FILE)
    parser.add_argument("--optimal-file", default=DEFAULT_OPTIMAL_FILE)
    parser.add_argument("--prediction-file", default=DEFAULT_PREDICTION_FILE)
    parser.add_argument("--mpg-file", default=DEFAULT_MPG_FILE)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--rollouts", type=int, default=DEFAULT_ROLLOUTS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--write-rollouts", action="store_true")
    parser.add_argument("--write-plot", action="store_true")
    args = parser.parse_args()
    if args.rollouts <= 0:
        raise SystemExit("--rollouts must be positive")

    completed_rows = read_csv(args.completed_file)
    score_ev_file_is_default = args.score_ev_file == DEFAULT_SCORE_EV_FILE
    optimal_file_is_default = args.optimal_file == DEFAULT_OPTIMAL_FILE
    score_row_values, optimal_row_values, score_path, optimal_path, used_snapshot = (
        load_matching_strategy_files(
            completed_rows,
            args.score_ev_file,
            args.optimal_file,
            allow_snapshot_fallback=score_ev_file_is_default
            and optimal_file_is_default,
        )
    )
    score_rows = score_ev_lookup(score_row_values)
    optimal_rows = optimal_lookup(optimal_row_values)

    strategies: dict[str, list[bookmaker_results.ScoredPick]] = {
        "always_0_0": fixed_strategy_picks("always_0_0", completed_rows, score_rows),
        "always_1_1": fixed_strategy_picks("always_1_1", completed_rows, score_rows),
        "underdog_1_0": fixed_strategy_picks("underdog_1_0", completed_rows, score_rows),
        "favorite_1_0": fixed_strategy_picks("favorite_1_0", completed_rows, score_rows),
        "bookmaker_injected_top1": bookmaker_picks(
            args.prediction_file, args.completed_file, args.mpg_file
        ),
        "optimal_current": optimal_strategy_picks(completed_rows, score_rows, optimal_rows),
    }

    rollups: dict[str, np.ndarray] = {}
    summaries: list[dict[str, object]] = []
    all_results: list[dict[str, object]] = []
    for index, (strategy, picks) in enumerate(strategies.items()):
        totals = bookmaker_results.simulate_totals(
            picks, args.rollouts, args.seed + index
        )
        rollups[strategy] = totals
        summaries.append(summary_row(strategy, picks, totals))
        all_results.extend(result_rows(strategy, picks))

    out_dir = Path(args.out_dir)
    write_csv(out_dir / "strategy_summary.csv", summaries, SUMMARY_FIELDS)
    write_csv(out_dir / "strategy_results.csv", all_results, RESULT_FIELDS)
    if args.write_rollouts:
        write_csv(
            out_dir / "total_rollouts.csv",
            [
                {
                    "strategy": strategy,
                    "rollout": rollout + 1,
                    "total_points": float(total),
                }
                for strategy, totals in rollups.items()
                for rollout, total in enumerate(totals)
            ],
            ["strategy", "rollout", "total_points"],
        )
    if args.write_plot:
        plot_results(out_dir / "points_distributions.png", summaries, rollups)

    print(f"Completed games analyzed: {len(completed_rows)}")
    if used_snapshot:
        print(
            "Default strategy files did not cover completed games; "
            f"using snapshot pair: {score_path}, {optimal_path}"
        )
    for row in summaries:
        print(
            f"{row['strategy']}: realized {float(row['realized_points']):.2f}, "
            f"EV {float(row['expected_points']):.2f}, "
            f"sim mean {float(row['simulated_mean']):.2f}, "
            f"percentile {float(row['realized_percentile']):.2%}"
        )
    print(f"Saved summary: {out_dir / 'strategy_summary.csv'}")
    print(f"Saved per-game results: {out_dir / 'strategy_results.csv'}")
    if args.write_rollouts:
        print(f"Saved rollouts: {out_dir / 'total_rollouts.csv'}")
    if args.write_plot:
        print(f"Saved plot: {out_dir / 'points_distributions.png'}")


if __name__ == "__main__":
    main()
