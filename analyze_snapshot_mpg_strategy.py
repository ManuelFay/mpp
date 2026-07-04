#!/usr/bin/env python3
"""Score and simulate historical compute_mpg strategy snapshots."""

from __future__ import annotations

import argparse
import csv
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

import compute_mpg_strategy


DEFAULT_SNAPSHOT_DIR = "data/mpg/strategy_snapshots"
DEFAULT_COMPLETED_FILE = "data/mpg/completed_games.csv"
DEFAULT_OUT_DIR = "data/analysis/strategy_simulations/compute_mpg_counterfactual"
DEFAULT_ROLLOUTS = 200_000
DEFAULT_SEED = 20260704

RESULT_FIELDS = [
    "snapshot_at_utc",
    "commence_time",
    "match",
    "selected_pick",
    "selected_score",
    "actual_score",
    "outcome_correct",
    "exact_score_correct",
    "base_points",
    "exact_bonus_points",
    "realized_points",
    "expected_points",
    "realized_minus_expected_points",
]

SUMMARY_FIELDS = [
    "completed_picks",
    "realized_points",
    "expected_points",
    "simulated_mean",
    "simulated_sd",
    "realized_percentile",
    "p10",
    "median",
    "p90",
]


@dataclass(frozen=True)
class SnapshotDecision:
    captured_at: datetime
    row: dict[str, str]


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_csv(path: str | Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fields,
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def snapshot_time(path: str | Path) -> datetime:
    stem = Path(path).stem
    timestamp = stem.removeprefix("mpg_optimal_strategy_")
    return datetime.strptime(timestamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def game_key(row: dict[str, str]) -> tuple[str, str]:
    home = row.get("matched_home_team") or row["home_team"]
    away = row.get("matched_away_team") or row["away_team"]
    return (
        compute_mpg_strategy.normalize_team(home),
        compute_mpg_strategy.normalize_team(away),
    )


def completed_key(row: dict[str, str]) -> tuple[str, str]:
    return (
        compute_mpg_strategy.normalize_team(row["home_team"]),
        compute_mpg_strategy.normalize_team(row["away_team"]),
    )


def available_mpg_rows(
    mpg_rows: list[dict[str, str]],
    probability_rows: list[dict[str, str]],
    exact_score_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    probability_keys = {
        (
            compute_mpg_strategy.normalize_team(row["home_team"]),
            compute_mpg_strategy.normalize_team(row["away_team"]),
        )
        for row in probability_rows
    }
    exact_score_keys = {
        (
            compute_mpg_strategy.normalize_team(row["home_team"]),
            compute_mpg_strategy.normalize_team(row["away_team"]),
        )
        for row in exact_score_rows
    }
    return [
        row
        for row in mpg_rows
        if (
            compute_mpg_strategy.normalize_team(row["home_team"]),
            compute_mpg_strategy.normalize_team(row["away_team"]),
        )
        in probability_keys
        and (
            compute_mpg_strategy.normalize_team(row["home_team"]),
            compute_mpg_strategy.normalize_team(row["away_team"]),
        )
        in exact_score_keys
    ]


def load_snapshot_decisions(snapshot_dir: str | Path) -> dict[tuple[str, str], list[SnapshotDecision]]:
    grouped: dict[tuple[str, str], list[SnapshotDecision]] = {}
    for path in sorted(Path(snapshot_dir).glob("*/*/mpg_optimal_strategy_*.csv")):
        captured_at = snapshot_time(path)
        for row in read_csv(path):
            grouped.setdefault(game_key(row), []).append(
                SnapshotDecision(captured_at=captured_at, row=row)
            )
    for decisions in grouped.values():
        decisions.sort(key=lambda decision: decision.captured_at)
    return grouped


def latest_decision(
    decisions: list[SnapshotDecision],
    commence_time: str,
    *,
    require_pre_kickoff: bool,
) -> SnapshotDecision | None:
    if not require_pre_kickoff:
        return decisions[-1] if decisions else None
    kickoff = parse_utc(commence_time)
    valid = [decision for decision in decisions if decision.captured_at < kickoff]
    return valid[-1] if valid else None


def selected_outcome(row: dict[str, str]) -> str:
    pick = str(row["optimal_pick"])
    if pick == "Draw":
        return "draw"
    if compute_mpg_strategy.normalize_team(pick) == compute_mpg_strategy.normalize_team(
        str(row.get("matched_home_team") or row["home_team"])
    ):
        return "home"
    if compute_mpg_strategy.normalize_team(pick) == compute_mpg_strategy.normalize_team(
        str(row.get("matched_away_team") or row["away_team"])
    ):
        return "away"
    raise ValueError(f"Cannot map optimal pick {pick!r} to an outcome")


def score_completed_decisions(
    strategy_rows: list[dict[str, str]],
    completed_rows: list[dict[str, str]],
) -> list[dict[str, object]]:
    completed = {completed_key(row): row for row in completed_rows}
    scored: list[dict[str, object]] = []
    for row in strategy_rows:
        key = game_key(row)
        completed_row = completed.get(key)
        selected = selected_outcome(row)
        base_points = float(row["optimal_pick_points"])
        expected_points = float(row["optimal_expected_points"])
        result = {
            "snapshot_at_utc": row.get("snapshot_at_utc", ""),
            "commence_time": completed_row.get("commence_time", "") if completed_row else "",
            "match": f"{row['home_team']} vs {row['away_team']}",
            "selected_pick": row["optimal_pick"],
            "selected_score": row["optimal_exact_score"],
            "actual_score": "",
            "outcome_correct": False,
            "exact_score_correct": False,
            "base_points": "",
            "exact_bonus_points": "",
            "realized_points": "",
            "expected_points": expected_points,
            "realized_minus_expected_points": "",
            "completed": False,
        }
        if completed_row is None:
            scored.append(result)
            continue

        actual_home = int(completed_row["home_score"])
        actual_away = int(completed_row["away_score"])
        actual_outcome = compute_mpg_strategy.score_outcome(actual_home, actual_away)
        actual_score = f"{actual_home}-{actual_away}"
        outcome_correct = selected == actual_outcome
        exact_score_correct = str(row["optimal_exact_score"]) == actual_score
        exact_bonus = (
            float(completed_row["actual_exact_bonus_points"]) if exact_score_correct else 0.0
        )
        realized = base_points + exact_bonus if outcome_correct else 0.0
        result.update(
            {
                "commence_time": completed_row.get("commence_time", ""),
                "actual_score": actual_score,
                "outcome_correct": outcome_correct,
                "exact_score_correct": exact_score_correct,
                "base_points": base_points if outcome_correct else 0.0,
                "exact_bonus_points": exact_bonus,
                "realized_points": realized,
                "realized_minus_expected_points": realized - expected_points,
                "completed": True,
            }
        )
        scored.append(result)
    return scored


def historical_scored_decisions(
    snapshot_dir: str | Path,
    completed_rows: list[dict[str, str]],
    *,
    require_pre_kickoff: bool = False,
) -> list[dict[str, object]]:
    decisions = load_snapshot_decisions(snapshot_dir)
    selected_rows: list[dict[str, str]] = []
    for completed in sorted(completed_rows, key=lambda row: row["commence_time"]):
        decision = latest_decision(
            decisions.get(completed_key(completed), []),
            completed["commence_time"],
            require_pre_kickoff=require_pre_kickoff,
        )
        if decision is None:
            continue
        row = dict(decision.row)
        row["snapshot_at_utc"] = decision.captured_at.isoformat().replace("+00:00", "Z")
        selected_rows.append(row)
    return score_completed_decisions(selected_rows, completed_rows)


def simulate_totals(rows: list[dict[str, object]], rollouts: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    totals = np.zeros(rollouts)
    for row in rows:
        outcome_probability = float(row["optimal_pick_probability"])
        exact_probability = float(row["optimal_exact_score_probability"])
        base_points = float(row["optimal_pick_points"])
        bonus_points = float(row["optimal_exact_bonus_points"])
        exact_probability = min(exact_probability, outcome_probability)
        outcome_only_probability = max(0.0, outcome_probability - exact_probability)
        miss_probability = max(0.0, 1.0 - outcome_probability)
        probabilities = np.array(
            [miss_probability, outcome_only_probability, exact_probability],
            dtype=float,
        )
        probabilities = probabilities / probabilities.sum()
        totals += rng.choice(
            [0.0, base_points, base_points + bonus_points],
            size=rollouts,
            p=probabilities,
        )
    return totals


def write_distribution_plot(path: str | Path, totals: np.ndarray, realized: float) -> None:
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
    box_ax.boxplot(
        totals,
        vert=False,
        widths=0.5,
        showfliers=False,
        patch_artist=True,
        boxprops={"facecolor": "#9ecae1", "edgecolor": "#174a7e"},
        medianprops={"color": "#174a7e", "linewidth": 2},
    )
    box_ax.scatter(
        [realized],
        [1],
        marker="D",
        s=80,
        color="#c62828",
        zorder=5,
        label=f"Resolved: {realized:.0f}",
    )
    box_ax.axvline(mean, color="#e66101", linewidth=2, label=f"Mean EV: {mean:.1f}")
    box_ax.set_yticks([])
    box_ax.set_title("Compute MPG strategy: resolved points vs simulated EV range")
    box_ax.legend(loc="upper left", ncol=2)

    hist_ax.hist(totals, bins=70, density=True, color="#9ecae1", edgecolor="white")
    colors = {"1": "#e6ab02", "2": "#7570b3"}
    for multiple in (1, 2):
        low = mean - multiple * sigma
        high = mean + multiple * sigma
        hist_ax.axvline(
            low, color=colors[str(multiple)], linestyle="--", linewidth=1.5
        )
        hist_ax.axvline(
            high,
            color=colors[str(multiple)],
            linestyle="--",
            linewidth=1.5,
            label=f"Mean ± {multiple}σ: {low:.0f} to {high:.0f}",
        )
    hist_ax.axvline(mean, color="#e66101", linewidth=2)
    hist_ax.axvline(realized, color="#c62828", linewidth=2.5)
    hist_ax.annotate(
        f"Resolved {realized:.0f}\n{percentile:.1%} percentile",
        xy=(realized, hist_ax.get_ylim()[1] * 0.72),
        xytext=(12, 0),
        textcoords="offset points",
        color="#c62828",
        fontweight="bold",
    )
    hist_ax.set_xlabel("Total points over completed games")
    hist_ax.set_ylabel("Simulated density")
    hist_ax.grid(axis="y", color="#e0e0e0", linewidth=0.8)
    hist_ax.legend(loc="upper right")
    fig.tight_layout()
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--completed-file", default=DEFAULT_COMPLETED_FILE)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--rollouts", type=int, default=DEFAULT_ROLLOUTS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--require-pre-kickoff", action="store_true")
    args = parser.parse_args()

    completed_rows = read_csv(args.completed_file)
    scored = historical_scored_decisions(
        args.snapshot_dir,
        completed_rows,
        require_pre_kickoff=args.require_pre_kickoff,
    )
    if not scored:
        raise SystemExit("No resolved compute strategy decisions found.")

    out_dir = Path(args.out_dir)
    result_path = out_dir / "compute_mpg_completed_results.csv"
    write_csv(result_path, scored, RESULT_FIELDS)

    simulation_rows = [
        dict(row)
        for row in load_selected_snapshot_rows(
            args.snapshot_dir,
            completed_rows,
            require_pre_kickoff=args.require_pre_kickoff,
        )
    ]
    totals = simulate_totals(simulation_rows, args.rollouts, args.seed)
    realized = sum(float(row["realized_points"]) for row in scored)
    expected = sum(float(row["expected_points"]) for row in scored)
    percentile = float((totals <= realized).mean())
    summary = [
        {
            "completed_picks": len(scored),
            "realized_points": realized,
            "expected_points": expected,
            "simulated_mean": float(totals.mean()),
            "simulated_sd": float(totals.std()),
            "realized_percentile": percentile,
            "p10": float(np.percentile(totals, 10)),
            "median": float(np.median(totals)),
            "p90": float(np.percentile(totals, 90)),
        }
    ]
    summary_path = out_dir / "compute_mpg_summary.csv"
    write_csv(summary_path, summary, SUMMARY_FIELDS)
    rollout_path = out_dir / "compute_mpg_total_rollouts.csv"
    write_csv(
        rollout_path,
        [{"rollout": index + 1, "total_points": float(total)} for index, total in enumerate(totals)],
        ["rollout", "total_points"],
    )
    plot_path = out_dir / "compute_mpg_luck_distribution.png"
    write_distribution_plot(plot_path, totals, realized)

    print(f"Completed compute MPG picks: {len(scored)}")
    print(f"Resolved points: {realized:.2f}")
    print(f"Logged expected value: {expected:.2f}")
    print(f"Resolved minus EV: {realized - expected:+.2f}")
    print(f"Simulation mean / standard deviation: {float(totals.mean()):.2f} / {float(totals.std()):.2f}")
    print(f"Resolved percentile: {percentile:.2%}")
    print(f"Saved per-game results: {result_path}")
    print(f"Saved summary: {summary_path}")
    print(f"Saved rollouts: {rollout_path}")
    print(f"Saved plot: {plot_path}")


def load_selected_snapshot_rows(
    snapshot_dir: str | Path,
    completed_rows: list[dict[str, str]],
    *,
    require_pre_kickoff: bool,
) -> list[dict[str, str]]:
    decisions = load_snapshot_decisions(snapshot_dir)
    rows: list[dict[str, str]] = []
    for completed in sorted(completed_rows, key=lambda row: row["commence_time"]):
        decision = latest_decision(
            decisions.get(completed_key(completed), []),
            completed["commence_time"],
            require_pre_kickoff=require_pre_kickoff,
        )
        if decision is not None:
            rows.append(dict(decision.row))
    return rows


if __name__ == "__main__":
    main()
