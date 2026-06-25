#!/usr/bin/env python3
"""Score bookmaker-injected top-1 picks and estimate their luck percentile."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bookmaker_injected_strategy


DEFAULT_PREDICTION_FILE = "data/bookmaker_injected/expected_mpg_top5.csv"
DEFAULT_COMPLETED_FILE = "data/mpg/completed_games.csv"
DEFAULT_MPG_FILE = "data/mpg/mpg.txt"
DEFAULT_OUT_DIR = "data/analysis/strategy_simulations/bookmaker_injected"
DEFAULT_ROLLOUTS = 200_000
DEFAULT_SEED = 20260615

RESULT_FIELDS = [
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


@dataclass(frozen=True)
class ScoredPick:
    match: str
    commence_time: str
    selected_score: str
    actual_score: str
    outcome_probability: float
    exact_score_probability: float
    conditional_bettor_share: float
    conditional_share_sigma: float
    base_points: float
    expected_points: float
    outcome_correct: bool
    exact_score_correct: bool
    exact_bonus_points: float
    realized_points: float
    payout_multiplier: float = 1.0


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_csv(
    path: Path, rows: list[dict[str, object]], fieldnames: list[str]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def normalize_team(team: str) -> str:
    return bookmaker_injected_strategy.normalize_team(team)


def parse_utc(value: str) -> dt.datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def top_pick_candidates(
    rows: list[dict[str, str]],
) -> dict[tuple[str, str], list[dict[str, str]]]:
    top_picks: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        if row["rank"] != "1":
            continue
        match = row["match"]
        if " vs " not in match:
            raise ValueError(f"Cannot parse match label {match!r}")
        home_team, away_team = match.split(" vs ", maxsplit=1)
        key = (normalize_team(home_team), normalize_team(away_team))
        top_picks.setdefault(key, []).append(row)
    for candidates in top_picks.values():
        candidates.sort(key=lambda row: parse_utc(row["logged_at_utc"]))
    return top_picks


def latest_valid_top_pick(
    candidates: list[dict[str, str]],
    commence_time: str,
    prediction_cutoff_utc: str | None = None,
    require_pre_kickoff: bool = False,
) -> dict[str, str] | None:
    cutoffs = []
    if require_pre_kickoff:
        cutoffs.append(parse_utc(commence_time))
    if prediction_cutoff_utc is not None:
        cutoffs.append(parse_utc(prediction_cutoff_utc))
    if not cutoffs:
        return candidates[-1] if candidates else None
    cutoff = min(cutoffs)
    valid = [
        row
        for row in candidates
        if parse_utc(row["logged_at_utc"]) < cutoff
    ]
    return valid[-1] if valid else None


def mpg_points_lookup(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, float]]:
    return {
        (normalize_team(row["home_team"]), normalize_team(row["away_team"])): {
            "home": float(row["home_odds"]),
            "draw": float(row["draw_odds"]),
            "away": float(row["away_odds"]),
        }
        for row in rows
    }


def score_completed_picks(
    prediction_rows: list[dict[str, str]],
    completed_rows: list[dict[str, str]],
    mpg_rows: list[dict[str, str]],
    prediction_cutoff_utc: str | None = None,
    require_pre_kickoff: bool = False,
) -> list[ScoredPick]:
    top_picks = top_pick_candidates(prediction_rows)
    points = mpg_points_lookup(mpg_rows)
    scored: list[ScoredPick] = []

    for completed in sorted(completed_rows, key=lambda row: row["commence_time"]):
        key = (
            normalize_team(completed["home_team"]),
            normalize_team(completed["away_team"]),
        )
        candidates = top_picks.get(key, [])
        prediction = latest_valid_top_pick(
            candidates,
            completed["commence_time"],
            prediction_cutoff_utc,
            require_pre_kickoff,
        )
        if prediction is None:
            continue
        if key not in points:
            raise ValueError(f"No MPG points found for {completed['home_team']} vs {completed['away_team']}")

        selected_outcome = prediction["outcome"]
        actual_home = int(completed["home_score"])
        actual_away = int(completed["away_score"])
        actual_outcome = bookmaker_injected_strategy.score_outcome(
            actual_home, actual_away
        )
        actual_score = f"{actual_home}-{actual_away}"
        outcome_correct = selected_outcome == actual_outcome
        exact_score_correct = prediction["score"] == actual_score
        base_points = points[key][selected_outcome]
        exact_bonus_points = (
            float(prediction["nominal_bonus_points"]) if exact_score_correct else 0.0
        )
        realized_points = (
            base_points + exact_bonus_points if outcome_correct else 0.0
        )
        scored.append(
            ScoredPick(
                match=prediction["match"],
                commence_time=completed["commence_time"],
                selected_score=prediction["score"],
                actual_score=actual_score,
                outcome_probability=float(prediction["outcome_probability"]),
                exact_score_probability=float(prediction["exact_score_probability"]),
                conditional_bettor_share=float(
                    prediction["conditional_bettor_share"]
                ),
                conditional_share_sigma=float(
                    prediction["conditional_share_sigma"]
                ),
                base_points=base_points,
                expected_points=float(prediction["total_ev"]),
                outcome_correct=outcome_correct,
                exact_score_correct=exact_score_correct,
                exact_bonus_points=exact_bonus_points,
                realized_points=realized_points,
            )
        )
    return scored


def sample_bonus_points(
    pick: ScoredPick, count: int, rng: np.random.Generator
) -> np.ndarray:
    shares = rng.normal(
        pick.conditional_bettor_share, pick.conditional_share_sigma, size=count
    )
    return np.select(
        [shares > 0.30, shares >= 0.20, shares >= 0.05, shares >= 0.005],
        [20.0, 30.0, 50.0, 70.0],
        default=100.0,
    )


def simulate_totals(
    picks: list[ScoredPick], rollouts: int, seed: int
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    totals = np.zeros(rollouts)
    for pick in picks:
        draws = rng.random(rollouts)
        exact = draws < pick.exact_score_probability
        outcome_only = (
            (draws >= pick.exact_score_probability)
            & (draws < pick.outcome_probability)
        )
        totals[outcome_only] += pick.base_points * pick.payout_multiplier
        exact_count = int(exact.sum())
        if exact_count:
            totals[exact] += (
                pick.base_points + sample_bonus_points(pick, exact_count, rng)
            ) * pick.payout_multiplier
    return totals


def result_rows(picks: list[ScoredPick]) -> list[dict[str, object]]:
    return [
        {
            "commence_time": pick.commence_time,
            "match": pick.match,
            "selected_score": pick.selected_score,
            "actual_score": pick.actual_score,
            "outcome_correct": pick.outcome_correct,
            "exact_score_correct": pick.exact_score_correct,
            "base_points": pick.base_points if pick.outcome_correct else 0.0,
            "exact_bonus_points": pick.exact_bonus_points,
            "realized_points": pick.realized_points,
            "expected_points": pick.expected_points,
            "realized_minus_expected": pick.realized_points
            - pick.expected_points,
        }
        for pick in picks
    ]


def write_plot(
    path: Path,
    totals: np.ndarray,
    realized: float,
    title: str = "Bookmaker-injected top-1 strategy: resolved points vs simulated EV range",
) -> None:
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
        [realized], [1], marker="D", s=80, color="#c62828", zorder=5,
        label=f"Resolved: {realized:.0f}",
    )
    box_ax.axvline(mean, color="#e66101", linewidth=2, label=f"Mean EV: {mean:.1f}")
    box_ax.set_yticks([])
    box_ax.set_title(title)
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
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prediction-file", default=DEFAULT_PREDICTION_FILE)
    parser.add_argument("--completed-file", default=DEFAULT_COMPLETED_FILE)
    parser.add_argument("--mpg-file", default=DEFAULT_MPG_FILE)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--rollouts", type=int, default=DEFAULT_ROLLOUTS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--prediction-cutoff-utc",
        help="Only include rank-1 predictions logged before this UTC timestamp.",
    )
    parser.add_argument(
        "--require-pre-kickoff",
        action="store_true",
        help="Only include rank-1 predictions logged before each match kickoff.",
    )
    parser.add_argument("--write-rollouts", action="store_true")
    parser.add_argument("--write-plot", action="store_true")
    args = parser.parse_args()
    if args.rollouts <= 0:
        raise SystemExit("--rollouts must be positive")

    picks = score_completed_picks(
        read_csv(args.prediction_file),
        read_csv(args.completed_file),
        read_csv(args.mpg_file),
        args.prediction_cutoff_utc,
        args.require_pre_kickoff,
    )
    if not picks:
        raise SystemExit("No completed games matched bookmaker-injected top-1 picks")

    totals = simulate_totals(picks, args.rollouts, args.seed)
    realized = sum(pick.realized_points for pick in picks)
    expected = sum(pick.expected_points for pick in picks)
    mean = float(totals.mean())
    sigma = float(totals.std())
    percentile = float(np.mean(totals <= realized))

    out_dir = Path(args.out_dir)
    results_path = out_dir / "completed_top1_results.csv"
    write_csv(results_path, result_rows(picks), RESULT_FIELDS)
    if args.write_rollouts:
        rollouts_path = out_dir / "top1_total_rollouts.csv"
        write_csv(
            rollouts_path,
            [
                {"rollout": index + 1, "total_points": float(total)}
                for index, total in enumerate(totals)
            ],
            ["rollout", "total_points"],
        )
        print(f"Saved rollouts: {rollouts_path}")
    if args.write_plot:
        plot_path = out_dir / "top1_luck_distribution.png"
        write_plot(plot_path, totals, realized)
        print(f"Saved plot: {plot_path}")

    print(f"Completed bookmaker top-1 picks: {len(picks)}")
    print(f"Realized points: {realized:.2f}")
    print(f"Logged expected points: {expected:.2f}")
    print(f"Realized minus EV: {realized - expected:+.2f}")
    print(f"Simulated mean / standard deviation: {mean:.2f} / {sigma:.2f}")
    print(f"Realized percentile (lower means unluckier): {percentile:.2%}")
    print(f"Mean ± 1σ: {mean - sigma:.2f} to {mean + sigma:.2f}")
    print(f"Mean ± 2σ: {mean - 2 * sigma:.2f} to {mean + 2 * sigma:.2f}")
    print(f"Saved per-game results: {results_path}")


if __name__ == "__main__":
    main()
