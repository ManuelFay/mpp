#!/usr/bin/env python3
"""
Run the exact-score model and MPG strategy across odds snapshots.

For each snapshot, this script:
  1. Builds market-implied game probabilities.
  2. Fits calibrated exact-score probabilities.
  3. Computes the MPG optimal strategy.

It then writes snapshot-level expected points and per-game strategy changes
between consecutive snapshots.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import compute_mpg_strategy
import odds_filters
import process_latest_odds


DEFAULT_SNAPSHOT_DIR = "data/odds_snapshots"
DEFAULT_SNAPSHOT_PREFIX = "world_cup_first_round_odds"
DEFAULT_MPG_FILE = "data/mpg/mpg.txt"
DEFAULT_COMPLETED_GAMES_FILE = "data/mpg/completed_games.csv"
DEFAULT_HISTORICAL_ODDS = "data/historical/odds_2022.csv"
DEFAULT_OUT_DIR = "data/analysis/mpg_snapshot_strategy"
DEFAULT_SIGNIFICANT_EV_DELTA = 1.0

SNAPSHOT_SUMMARY_FIELDS = [
    "snapshot_id",
    "snapshot_file",
    "input_rows",
    "probability_games",
    "exact_score_games",
    "mpg_games",
    "total_expected_points",
    "avg_expected_points",
    "min_expected_points",
    "max_expected_points",
    "strategies_changed_by_exact_bonus",
    "completed_games",
    "completed_expected_points",
    "realized_points",
    "realized_minus_expected_points",
]

DECISION_FIELDS = [
    "snapshot_id",
    "snapshot_file",
    *compute_mpg_strategy.OUT_FIELDS,
    "completed",
    "actual_score",
    "outcome_correct",
    "exact_score_correct",
    "realized_base_points",
    "realized_exact_bonus_points",
    "realized_points",
    "realized_minus_expected_points",
]

CHANGE_FIELDS = [
    "from_snapshot_id",
    "to_snapshot_id",
    "home_team",
    "away_team",
    "previous_optimal_pick",
    "new_optimal_pick",
    "previous_exact_score",
    "new_exact_score",
    "previous_expected_points",
    "new_expected_points",
    "expected_points_delta",
    "abs_expected_points_delta",
    "previous_edge",
    "new_edge",
    "edge_delta",
    "decision_changed",
    "significant_expectancy_change",
    "previous_home_probability",
    "new_home_probability",
    "previous_draw_probability",
    "new_draw_probability",
    "previous_away_probability",
    "new_away_probability",
]


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: str | Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def snapshot_sort_key(path: Path) -> tuple[str, str]:
    match = re.search(r"(\d{8}T\d{6}Z)", path.name)
    if match:
        return match.group(1), path.as_posix()
    return path.stem, path.as_posix()


def snapshot_id(path: Path) -> str:
    match = re.search(r"(\d{8}T\d{6}Z)", path.name)
    if match:
        return match.group(1)
    return path.stem


def discover_snapshots(snapshot_dir: str | Path, snapshot_prefix: str, include_latest: bool) -> list[Path]:
    root = Path(snapshot_dir)
    paths = sorted(root.rglob("*.csv"), key=snapshot_sort_key)
    if not include_latest:
        paths = [path for path in paths if path.name != "latest.csv"]
    return [
        path
        for path in paths
        if path.name == "latest.csv" or path.name == f"{snapshot_prefix}_{snapshot_id(path)}.csv"
    ]


def decision_key(row: dict[str, object]) -> tuple[str, str]:
    return str(row["matched_home_team"]), str(row["matched_away_team"])


def completed_game_lookup(
    completed_rows: list[dict[str, str]],
) -> dict[tuple[str, str], dict[str, str]]:
    return {
        (
            compute_mpg_strategy.normalize_team(row["home_team"]),
            compute_mpg_strategy.normalize_team(row["away_team"]),
        ): row
        for row in completed_rows
    }


def score_completed_decisions(
    strategy_rows: list[dict[str, object]],
    completed_rows: list[dict[str, str]],
) -> list[dict[str, object]]:
    completed_by_game = completed_game_lookup(completed_rows)
    scored_rows: list[dict[str, object]] = []

    for row in strategy_rows:
        scored = dict(row)
        completed = completed_by_game.get(decision_key(row))
        if completed is None:
            scored.update(
                {
                    "completed": False,
                    "actual_score": "",
                    "outcome_correct": "",
                    "exact_score_correct": "",
                    "realized_base_points": "",
                    "realized_exact_bonus_points": "",
                    "realized_points": "",
                    "realized_minus_expected_points": "",
                }
            )
            scored_rows.append(scored)
            continue

        home_score = int(completed["home_score"])
        away_score = int(completed["away_score"])
        actual_outcome = compute_mpg_strategy.score_outcome(home_score, away_score)
        selected_pick = str(row["optimal_pick"])
        if selected_pick == "Draw":
            selected_outcome = "draw"
        elif compute_mpg_strategy.normalize_team(selected_pick) == str(row["matched_home_team"]):
            selected_outcome = "home"
        elif compute_mpg_strategy.normalize_team(selected_pick) == str(row["matched_away_team"]):
            selected_outcome = "away"
        else:
            raise ValueError(
                f"Cannot map optimal pick {selected_pick!r} for "
                f"{row['home_team']} vs {row['away_team']}"
            )

        outcome_correct = selected_outcome == actual_outcome
        exact_score_correct = str(row["optimal_exact_score"]) == completed["final_score"]
        base_points = float(row["optimal_pick_points"]) if outcome_correct else 0.0
        exact_bonus_points = (
            float(completed["actual_exact_bonus_points"]) if exact_score_correct else 0.0
        )
        realized_points = base_points + exact_bonus_points
        scored.update(
            {
                "completed": True,
                "actual_score": completed["final_score"],
                "outcome_correct": outcome_correct,
                "exact_score_correct": exact_score_correct,
                "realized_base_points": base_points,
                "realized_exact_bonus_points": exact_bonus_points,
                "realized_points": realized_points,
                "realized_minus_expected_points": (
                    realized_points - float(row["optimal_expected_points"])
                ),
            }
        )
        scored_rows.append(scored)

    return scored_rows


def available_mpg_rows(
    mpg_rows: list[dict[str, str]],
    probability_rows: list[dict[str, object]],
    exact_score_rows: list[dict[str, object]],
) -> list[dict[str, str]]:
    probability_games = {
        (str(row["home_team"]), str(row["away_team"])) for row in probability_rows
    }
    exact_score_games = {
        (str(row["home_team"]), str(row["away_team"])) for row in exact_score_rows
    }
    available_games = probability_games & exact_score_games
    return [
        row
        for row in mpg_rows
        if (
            compute_mpg_strategy.normalize_team(row["home_team"]),
            compute_mpg_strategy.normalize_team(row["away_team"]),
        )
        in available_games
    ]


def process_snapshot(
    snapshot_path: Path,
    mpg_rows: list[dict[str, str]],
    calibration_multipliers: dict[str, float],
    market: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    rows = odds_filters.filter_snapshot_rows(process_latest_odds.read_rows(snapshot_path))
    probability_rows = process_latest_odds.process_rows(rows, market)
    exact_score_rows = process_latest_odds.process_exact_scores(rows, market)
    calibrated_exact_score_rows = process_latest_odds.calibrate_exact_score_rows(
        exact_score_rows,
        calibration_multipliers,
    )
    snapshot_mpg_rows = available_mpg_rows(
        mpg_rows,
        probability_rows,
        calibrated_exact_score_rows,
    )
    strategy_rows = compute_mpg_strategy.compute_strategy(
        snapshot_mpg_rows,
        probability_rows,
        calibrated_exact_score_rows,
    )
    return rows, probability_rows, calibrated_exact_score_rows, strategy_rows


def summarize_snapshot(
    snapshot_path: Path,
    raw_rows: list[dict[str, object]],
    probability_rows: list[dict[str, object]],
    exact_score_rows: list[dict[str, object]],
    strategy_rows: list[dict[str, object]],
) -> dict[str, object]:
    expected_points = [float(row["optimal_expected_points"]) for row in strategy_rows]
    total_expected_points = sum(expected_points)
    completed_rows = [row for row in strategy_rows if row.get("completed") is True]
    completed_expected_points = sum(
        float(row["optimal_expected_points"]) for row in completed_rows
    )
    realized_points = sum(float(row["realized_points"]) for row in completed_rows)
    return {
        "snapshot_id": snapshot_id(snapshot_path),
        "snapshot_file": snapshot_path.as_posix(),
        "input_rows": len(raw_rows),
        "probability_games": len(probability_rows),
        "exact_score_games": len(exact_score_rows),
        "mpg_games": len(strategy_rows),
        "total_expected_points": total_expected_points,
        "avg_expected_points": total_expected_points / len(expected_points) if expected_points else 0.0,
        "min_expected_points": min(expected_points) if expected_points else 0.0,
        "max_expected_points": max(expected_points) if expected_points else 0.0,
        "strategies_changed_by_exact_bonus": sum(
            str(row["strategy_changed_by_exact_bonus"]) == "True" or row["strategy_changed_by_exact_bonus"] is True
            for row in strategy_rows
        ),
        "completed_games": len(completed_rows),
        "completed_expected_points": completed_expected_points,
        "realized_points": realized_points,
        "realized_minus_expected_points": realized_points - completed_expected_points,
    }


def compare_strategy_rows(
    previous_snapshot: Path,
    current_snapshot: Path,
    previous_rows: list[dict[str, object]],
    current_rows: list[dict[str, object]],
    significant_ev_delta: float,
) -> list[dict[str, object]]:
    previous_by_game = {decision_key(row): row for row in previous_rows}
    current_by_game = {decision_key(row): row for row in current_rows}
    changes: list[dict[str, object]] = []

    for key in sorted(previous_by_game.keys() & current_by_game.keys()):
        previous = previous_by_game[key]
        current = current_by_game[key]
        previous_ev = float(previous["optimal_expected_points"])
        current_ev = float(current["optimal_expected_points"])
        ev_delta = current_ev - previous_ev
        decision_changed = (
            previous["optimal_pick"] != current["optimal_pick"]
            or previous["optimal_exact_score"] != current["optimal_exact_score"]
        )
        significant_expectancy_change = abs(ev_delta) >= significant_ev_delta
        if not decision_changed and not significant_expectancy_change:
            continue

        changes.append(
            {
                "from_snapshot_id": snapshot_id(previous_snapshot),
                "to_snapshot_id": snapshot_id(current_snapshot),
                "home_team": current["home_team"],
                "away_team": current["away_team"],
                "previous_optimal_pick": previous["optimal_pick"],
                "new_optimal_pick": current["optimal_pick"],
                "previous_exact_score": previous["optimal_exact_score"],
                "new_exact_score": current["optimal_exact_score"],
                "previous_expected_points": previous_ev,
                "new_expected_points": current_ev,
                "expected_points_delta": ev_delta,
                "abs_expected_points_delta": abs(ev_delta),
                "previous_edge": previous["expected_points_edge"],
                "new_edge": current["expected_points_edge"],
                "edge_delta": float(current["expected_points_edge"]) - float(previous["expected_points_edge"]),
                "decision_changed": decision_changed,
                "significant_expectancy_change": significant_expectancy_change,
                "previous_home_probability": previous["home_probability"],
                "new_home_probability": current["home_probability"],
                "previous_draw_probability": previous["draw_probability"],
                "new_draw_probability": current["draw_probability"],
                "previous_away_probability": previous["away_probability"],
                "new_away_probability": current["away_probability"],
            }
        )

    return sorted(changes, key=lambda row: float(row["abs_expected_points_delta"]), reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument(
        "--snapshot-prefix",
        default=DEFAULT_SNAPSHOT_PREFIX,
        help="Only analyze timestamped CSVs in this exact filename series.",
    )
    parser.add_argument("--mpg-file", default=DEFAULT_MPG_FILE)
    parser.add_argument("--completed-games-file", default=DEFAULT_COMPLETED_GAMES_FILE)
    parser.add_argument("--historical-odds-file", default=DEFAULT_HISTORICAL_ODDS)
    parser.add_argument("--market", default=process_latest_odds.DEFAULT_MARKET)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--significant-ev-delta", type=float, default=DEFAULT_SIGNIFICANT_EV_DELTA)
    parser.add_argument("--include-latest", action="store_true")
    args = parser.parse_args()

    snapshots = discover_snapshots(args.snapshot_dir, args.snapshot_prefix, args.include_latest)
    if not snapshots:
        raise SystemExit(f"No snapshot CSV files found under {args.snapshot_dir}")

    mpg_rows = compute_mpg_strategy.read_csv(args.mpg_file)
    completed_rows = compute_mpg_strategy.read_csv(args.completed_games_file)
    calibration_multipliers, _ = process_latest_odds.learn_score_shape_calibration(args.historical_odds_file)

    summary_rows: list[dict[str, object]] = []
    all_decision_rows: list[dict[str, object]] = []
    all_change_rows: list[dict[str, object]] = []
    previous_snapshot: Path | None = None
    previous_strategy_rows: list[dict[str, object]] | None = None

    for snapshot_path in snapshots:
        raw_rows, probability_rows, exact_score_rows, strategy_rows = process_snapshot(
            snapshot_path,
            mpg_rows,
            calibration_multipliers,
            args.market,
        )
        strategy_rows = score_completed_decisions(strategy_rows, completed_rows)
        current_snapshot_id = snapshot_id(snapshot_path)
        summary_rows.append(summarize_snapshot(snapshot_path, raw_rows, probability_rows, exact_score_rows, strategy_rows))
        all_decision_rows.extend(
            {
                "snapshot_id": current_snapshot_id,
                "snapshot_file": snapshot_path.as_posix(),
                **row,
            }
            for row in strategy_rows
        )

        if previous_snapshot is not None and previous_strategy_rows is not None:
            all_change_rows.extend(
                compare_strategy_rows(
                    previous_snapshot,
                    snapshot_path,
                    previous_strategy_rows,
                    strategy_rows,
                    args.significant_ev_delta,
                )
            )

        previous_snapshot = snapshot_path
        previous_strategy_rows = strategy_rows

    out_dir = Path(args.out_dir)
    write_csv(out_dir / "snapshot_expected_points.csv", summary_rows, SNAPSHOT_SUMMARY_FIELDS)
    write_csv(out_dir / "snapshot_strategy_decisions.csv", all_decision_rows, DECISION_FIELDS)
    write_csv(out_dir / "snapshot_strategy_changes.csv", all_change_rows, CHANGE_FIELDS)

    print(f"Snapshots processed: {len(snapshots)}")
    for row in summary_rows:
        print(f"{row['snapshot_id']}: {float(row['total_expected_points']):.2f} expected points")
    print(f"Strategy/expectancy changes written: {len(all_change_rows)}")
    print(f"Saved summary: {out_dir / 'snapshot_expected_points.csv'}")
    print(f"Saved decisions: {out_dir / 'snapshot_strategy_decisions.csv'}")
    print(f"Saved changes: {out_dir / 'snapshot_strategy_changes.csv'}")


if __name__ == "__main__":
    main()
