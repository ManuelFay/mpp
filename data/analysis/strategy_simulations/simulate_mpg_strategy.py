#!/usr/bin/env python3
"""
Compare the MPG expected-value optimal strategy with a representative player.

Each rollout represents one tournament realization and one player sampled from
the published MPG pick distribution:

  * Completed match outcomes and scores are read from completed_games.csv.
  * Unresolved match outcomes and scores are sampled from the model.
  * Population picks are sampled from home_pct/draw_pct/away_pct, with exact
    scores sampled from the behavior-adjusted bettor-share estimate within
    their chosen outcome.
  * The expected-value optimal picks are produced by compute_mpg_strategy.py.

The explicit score grid is 0-0 through 4-4. Out-of-grid actual scores can
deliver result points but cannot deliver an exact-score bonus.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import compute_mpg_strategy


DEFAULT_MPG_FILE = compute_mpg_strategy.DEFAULT_MPG_FILE
DEFAULT_PROBABILITY_FILE = compute_mpg_strategy.DEFAULT_PROBABILITY_FILE
DEFAULT_EXACT_SCORE_FILE = compute_mpg_strategy.DEFAULT_EXACT_SCORE_FILE
DEFAULT_BETTOR_MULTIPLIER_FILE = compute_mpg_strategy.DEFAULT_BETTOR_MULTIPLIER_FILE
DEFAULT_COMPLETED_GAMES_FILE = "data/mpg/completed_games.csv"
DEFAULT_OUT_DIR = "data/analysis/strategy_simulations/mpg_simulation"
DEFAULT_ROLLOUTS = 10_000
DEFAULT_SEED = 20260526
DEFAULT_EVENT_OFFSET = compute_mpg_strategy.DEFAULT_STRATEGY_EVENT_OFFSET
DEFAULT_EVENT_LIMIT = compute_mpg_strategy.DEFAULT_STRATEGY_EVENT_LIMIT
SCORE_GRID_MAX = 4
OUTCOMES = ("home", "draw", "away")
OUTCOME_TO_ID = {outcome: index for index, outcome in enumerate(OUTCOMES)}

PROGRESS_FIELDS = [
    "games_played",
    "population_mean_points",
    "population_p10_points",
    "population_median_points",
    "population_p90_points",
    "optimal_mean_points",
    "optimal_p10_points",
    "optimal_median_points",
    "optimal_p90_points",
    "optimal_mean_edge",
    "optimal_ahead_probability",
    "tie_probability",
]

FINAL_FIELDS = [
    "rollout",
    "population_points",
    "optimal_points",
    "optimal_edge",
]


@dataclass
class Game:
    event_id: str
    label: str
    result_probabilities: np.ndarray
    population_pick_probabilities: np.ndarray
    points: np.ndarray
    actual_score_probabilities: tuple[np.ndarray, np.ndarray, np.ndarray]
    population_score_probabilities: tuple[np.ndarray, np.ndarray, np.ndarray]
    score_bonus_points: tuple[np.ndarray, np.ndarray, np.ndarray]
    optimal_outcome: int
    optimal_score_index: int
    optimal_bonus_points: float
    actual_outcome: int | None = None
    actual_score_index: int | None = None
    actual_exact_bonus_points: float | None = None


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_population_share(value: str) -> float:
    return float(value.strip().removesuffix("%"))


def normalized(values: list[float] | np.ndarray, label: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    total = float(array.sum())
    if total <= 0:
        raise ValueError(f"Cannot normalize empty probability distribution for {label}")
    return array / total


def explicit_scores_for_outcome(outcome: str) -> list[tuple[int, int]]:
    return [
        (home_goals, away_goals)
        for home_goals in range(SCORE_GRID_MAX + 1)
        for away_goals in range(SCORE_GRID_MAX + 1)
        if compute_mpg_strategy.score_outcome(home_goals, away_goals) == outcome
    ]


def pick_to_outcome(pick: str, mpg_row: dict[str, str]) -> str:
    if pick == mpg_row["home_team"]:
        return "home"
    if pick == mpg_row["away_team"]:
        return "away"
    if pick == "Draw":
        return "draw"
    raise ValueError(f"Unknown strategy pick {pick!r} for {mpg_row['home_team']} vs {mpg_row['away_team']}")


def build_games(
    mpg_rows: list[dict[str, str]],
    probability_rows: list[dict[str, str]],
    exact_score_rows: list[dict[str, str]],
    completed_rows: list[dict[str, str]] | None = None,
    bettor_multipliers: dict[str, float] | None = None,
) -> tuple[list[Game], list[dict[str, str | float]]]:
    bettor_multipliers = (
        compute_mpg_strategy.load_bettor_behavior_multipliers(
            DEFAULT_BETTOR_MULTIPLIER_FILE
        )
        if bettor_multipliers is None
        else bettor_multipliers
    )
    probabilities = compute_mpg_strategy.probability_lookup(probability_rows)
    exact_scores = compute_mpg_strategy.exact_score_lookup(exact_score_rows)
    strategy_rows = compute_mpg_strategy.compute_strategy(
        mpg_rows, probability_rows, exact_score_rows, bettor_multipliers
    )
    strategy_by_game = {
        (str(row["home_team"]), str(row["away_team"])): row for row in strategy_rows
    }
    completed_by_event = {
        row["event_id"]: row for row in (completed_rows or [])
    }
    games: list[Game] = []

    for mpg_row in mpg_rows:
        matched_home = compute_mpg_strategy.normalize_team(mpg_row["home_team"])
        matched_away = compute_mpg_strategy.normalize_team(mpg_row["away_team"])
        probability_row = probabilities[(matched_home, matched_away)]
        exact_row = exact_scores[(matched_home, matched_away)]
        strategy_row = strategy_by_game[(mpg_row["home_team"], mpg_row["away_team"])]

        result_probabilities = normalized(
            [
                float(probability_row["home_probability"]),
                float(probability_row["draw_probability"]),
                float(probability_row["away_probability"]),
            ],
            "market result probabilities",
        )
        population_pick_probabilities = normalized(
            [
                parse_population_share(mpg_row["home_pct"]),
                parse_population_share(mpg_row["draw_pct"]),
                parse_population_share(mpg_row["away_pct"]),
            ],
            "population result picks",
        )
        points = np.array(
            [
                float(mpg_row["home_odds"]),
                float(mpg_row["draw_odds"]),
                float(mpg_row["away_odds"]),
            ]
        )

        actual_score_probabilities: list[np.ndarray] = []
        population_score_probabilities: list[np.ndarray] = []
        score_bonus_points: list[np.ndarray] = []
        for outcome in OUTCOMES:
            explicit_scores = explicit_scores_for_outcome(outcome)
            bettor_shares = compute_mpg_strategy.bettor_share_estimates(
                exact_row, outcome, bettor_multipliers
            )
            explicit_mass = np.array(
                [
                    float(exact_row[f"score_{home_goals}_{away_goals}_probability"])
                    for home_goals, away_goals in explicit_scores
                ]
            )
            other_column = (
                f"other_{outcome}_win_probability"
                if outcome in {"home", "away"}
                else "other_draw_probability"
            )
            other_mass = float(exact_row[other_column])
            actual_score_probabilities.append(
                normalized([*explicit_mass, other_mass], f"actual scores for {outcome}")
            )
            population_score_probabilities.append(
                normalized(
                    [
                        bettor_shares[f"{home_goals}-{away_goals}"][
                            "conditional_probability"
                        ]
                        for home_goals, away_goals in explicit_scores
                    ],
                    f"population exact-score picks for {outcome}",
                )
            )
            score_bonus_points.append(
                np.array(
                    [
                        compute_mpg_strategy.bonus_for_conditional_probability(
                            bettor_shares[f"{home_goals}-{away_goals}"][
                                "conditional_probability"
                            ]
                        )[1]
                        for home_goals, away_goals in explicit_scores
                    ]
                )
            )

        optimal_outcome = OUTCOME_TO_ID[pick_to_outcome(str(strategy_row["optimal_pick"]), mpg_row)]
        optimal_home_goals, optimal_away_goals = (
            int(value) for value in str(strategy_row["optimal_exact_score"]).split("-")
        )
        matching_scores = explicit_scores_for_outcome(OUTCOMES[optimal_outcome])
        optimal_score_index = matching_scores.index((optimal_home_goals, optimal_away_goals))
        event_id = probability_row["event_id"]
        completed_row = completed_by_event.get(event_id)
        actual_outcome: int | None = None
        actual_score_index: int | None = None
        actual_exact_bonus_points: float | None = None
        if completed_row is not None:
            actual_home_goals = int(completed_row["home_score"])
            actual_away_goals = int(completed_row["away_score"])
            actual_outcome = OUTCOME_TO_ID[
                compute_mpg_strategy.score_outcome(actual_home_goals, actual_away_goals)
            ]
            actual_scores = explicit_scores_for_outcome(OUTCOMES[actual_outcome])
            try:
                actual_score_index = actual_scores.index((actual_home_goals, actual_away_goals))
            except ValueError:
                actual_score_index = len(actual_scores)
            actual_exact_bonus_points = float(completed_row["actual_exact_bonus_points"])

        games.append(
            Game(
                event_id=event_id,
                label=f"{mpg_row['home_team']} vs {mpg_row['away_team']}",
                result_probabilities=result_probabilities,
                population_pick_probabilities=population_pick_probabilities,
                points=points,
                actual_score_probabilities=tuple(actual_score_probabilities),
                population_score_probabilities=tuple(population_score_probabilities),
                score_bonus_points=tuple(score_bonus_points),
                optimal_outcome=optimal_outcome,
                optimal_score_index=optimal_score_index,
                optimal_bonus_points=float(strategy_row["optimal_exact_bonus_points"]),
                actual_outcome=actual_outcome,
                actual_score_index=actual_score_index,
                actual_exact_bonus_points=actual_exact_bonus_points,
            )
        )

    return games, strategy_rows


def run_rollouts(games: list[Game], rollouts: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    population_cumulative = np.zeros((rollouts, len(games)))
    optimal_cumulative = np.zeros((rollouts, len(games)))
    population_total = np.zeros(rollouts)
    optimal_total = np.zeros(rollouts)

    for game_index, game in enumerate(games):
        if game.actual_outcome is None:
            actual_outcomes = rng.choice(
                len(OUTCOMES), size=rollouts, p=game.result_probabilities
            )
        else:
            actual_outcomes = np.full(rollouts, game.actual_outcome, dtype=int)
        population_outcomes = rng.choice(
            len(OUTCOMES), size=rollouts, p=game.population_pick_probabilities
        )
        actual_scores = np.full(rollouts, -1, dtype=int)
        population_scores = np.full(rollouts, -1, dtype=int)

        for outcome_id in range(len(OUTCOMES)):
            actual_mask = actual_outcomes == outcome_id
            actual_count = int(actual_mask.sum())
            if actual_count:
                if game.actual_score_index is None:
                    actual_scores[actual_mask] = rng.choice(
                        len(game.actual_score_probabilities[outcome_id]),
                        size=actual_count,
                        p=game.actual_score_probabilities[outcome_id],
                    )
                else:
                    actual_scores[actual_mask] = game.actual_score_index
            population_mask = population_outcomes == outcome_id
            population_count = int(population_mask.sum())
            if population_count:
                population_scores[population_mask] = rng.choice(
                    len(game.population_score_probabilities[outcome_id]),
                    size=population_count,
                    p=game.population_score_probabilities[outcome_id],
                )

        population_correct = population_outcomes == actual_outcomes
        population_game_points = np.where(population_correct, game.points[population_outcomes], 0.0)
        population_exact = population_correct & (population_scores == actual_scores)
        for outcome_id in range(len(OUTCOMES)):
            exact_mask = population_exact & (population_outcomes == outcome_id)
            if np.any(exact_mask):
                if game.actual_exact_bonus_points is None:
                    population_game_points[exact_mask] += game.score_bonus_points[outcome_id][
                        population_scores[exact_mask]
                    ]
                else:
                    population_game_points[exact_mask] += game.actual_exact_bonus_points

        optimal_correct = actual_outcomes == game.optimal_outcome
        optimal_game_points = np.where(optimal_correct, game.points[game.optimal_outcome], 0.0)
        optimal_exact = optimal_correct & (actual_scores == game.optimal_score_index)
        optimal_bonus_points = (
            game.optimal_bonus_points
            if game.actual_exact_bonus_points is None
            else game.actual_exact_bonus_points
        )
        optimal_game_points[optimal_exact] += optimal_bonus_points

        population_total += population_game_points
        optimal_total += optimal_game_points
        population_cumulative[:, game_index] = population_total
        optimal_cumulative[:, game_index] = optimal_total

    return population_cumulative, optimal_cumulative


def summarize_progress(population: np.ndarray, optimal: np.ndarray) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for game_index in range(population.shape[1]):
        crowd = population[:, game_index]
        strategy = optimal[:, game_index]
        edge = strategy - crowd
        rows.append(
            {
                "games_played": game_index + 1,
                "population_mean_points": float(crowd.mean()),
                "population_p10_points": float(np.percentile(crowd, 10)),
                "population_median_points": float(np.median(crowd)),
                "population_p90_points": float(np.percentile(crowd, 90)),
                "optimal_mean_points": float(strategy.mean()),
                "optimal_p10_points": float(np.percentile(strategy, 10)),
                "optimal_median_points": float(np.median(strategy)),
                "optimal_p90_points": float(np.percentile(strategy, 90)),
                "optimal_mean_edge": float(edge.mean()),
                "optimal_ahead_probability": float(np.mean(edge > 0)),
                "tie_probability": float(np.mean(edge == 0)),
            }
        )
    return rows


def final_rollout_rows(population: np.ndarray, optimal: np.ndarray) -> list[dict[str, object]]:
    crowd = population[:, -1]
    strategy = optimal[:, -1]
    return [
        {
            "rollout": rollout + 1,
            "population_points": float(crowd[rollout]),
            "optimal_points": float(strategy[rollout]),
            "optimal_edge": float(strategy[rollout] - crowd[rollout]),
        }
        for rollout in range(population.shape[0])
    ]


def write_plot(path: Path, population: np.ndarray, optimal: np.ndarray) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpp-matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    game_numbers = np.arange(1, population.shape[1] + 1)
    fig, ax = plt.subplots(figsize=(12, 7))
    density = ax.hexbin(
        np.tile(game_numbers, population.shape[0]),
        population.ravel(),
        gridsize=(population.shape[1] * 3, 55),
        bins="log",
        mincnt=1,
        cmap="Blues",
    )
    optimal_mean = optimal.mean(axis=0)
    optimal_p10 = np.percentile(optimal, 10, axis=0)
    optimal_p90 = np.percentile(optimal, 90, axis=0)
    population_mean = population.mean(axis=0)
    ax.plot(game_numbers, population_mean, color="#174a7e", linewidth=1.8, label="Population mean")
    ax.fill_between(
        game_numbers,
        optimal_p10,
        optimal_p90,
        color="#e66101",
        alpha=0.16,
        label="EV-optimal 10th-90th percentile",
    )
    ax.plot(game_numbers, optimal_mean, color="#e66101", linewidth=2.6, label="EV-optimal mean")
    colorbar = fig.colorbar(density, ax=ax)
    colorbar.set_label("Population rollout density (log count)")
    ax.set_title("MPG simulation: representative population player vs EV-optimal strategy")
    ax.set_xlabel("Games played")
    ax.set_ylabel("Cumulative points")
    ax.set_xticks(game_numbers)
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.8)
    ax.legend(loc="upper left")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_final_distribution_plot(path: Path, population: np.ndarray, optimal: np.ndarray) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpp-matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    population_final = population[:, -1]
    optimal_final = optimal[:, -1]
    bins = np.linspace(
        min(population_final.min(), optimal_final.min()),
        max(population_final.max(), optimal_final.max()),
        48,
    )
    fig, ax = plt.subplots(figsize=(11, 6.5))
    series = [
        ("Population player", population_final, "#7c3aed", "#4c1d95"),
        ("Compute MPG optimal", optimal_final, "#0891b2", "#155e75"),
    ]
    for label, totals, color, marker_color in series:
        mean = float(totals.mean())
        p10 = float(np.percentile(totals, 10))
        p90 = float(np.percentile(totals, 90))
        ax.hist(
            totals,
            bins=bins,
            density=True,
            alpha=0.30,
            color=color,
            edgecolor="none",
            label=f"{label} distribution",
        )
        ax.hist(
            totals,
            bins=bins,
            density=True,
            histtype="step",
            linewidth=2.3,
            color=color,
        )
        ax.axvline(
            mean,
            color=marker_color,
            linewidth=2.4,
            label=f"{label} mean {mean:.0f} (p10-p90 {p10:.0f}-{p90:.0f})",
        )

    ax.set_title("Round 3 simulated point distribution", fontsize=16, fontweight="bold", pad=14)
    ax.set_xlabel("Total points over 24 round-3 games")
    ax.set_ylabel("Probability density")
    ax.grid(axis="y", color="#e5e7eb", linewidth=0.9)
    ax.grid(axis="x", color="#f3f4f6", linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#9ca3af")
    ax.tick_params(colors="#374151")
    ax.legend(
        frameon=True,
        facecolor="white",
        edgecolor="#d1d5db",
        framealpha=0.92,
        loc="upper right",
    )
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mpg-file", default=DEFAULT_MPG_FILE)
    parser.add_argument("--probability-file", default=DEFAULT_PROBABILITY_FILE)
    parser.add_argument("--exact-score-file", default=DEFAULT_EXACT_SCORE_FILE)
    parser.add_argument("--bettor-multiplier-file", default=DEFAULT_BETTOR_MULTIPLIER_FILE)
    parser.add_argument("--completed-games-file", default=DEFAULT_COMPLETED_GAMES_FILE)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--event-offset",
        type=int,
        default=DEFAULT_EVENT_OFFSET,
        help="Number of schedule-sorted MPG games to skip. Defaults to the current compute strategy window.",
    )
    parser.add_argument(
        "--event-limit",
        type=int,
        default=DEFAULT_EVENT_LIMIT,
        help="Number of schedule-sorted MPG games to simulate. Use 0 for all remaining games.",
    )
    parser.add_argument("--rollouts", type=int, default=DEFAULT_ROLLOUTS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--write-rollouts", action="store_true")
    parser.add_argument("--write-plot", action="store_true")
    args = parser.parse_args()

    if args.rollouts <= 0:
        raise SystemExit("--rollouts must be positive")
    if args.event_offset < 0 or args.event_limit < 0:
        raise SystemExit("Event offsets and limits must be non-negative")

    all_mpg_rows = compute_mpg_strategy.read_csv(args.mpg_file)
    mpg_rows = compute_mpg_strategy.select_game_window(
        all_mpg_rows,
        offset=args.event_offset,
        limit=None if args.event_limit == 0 else args.event_limit,
    )
    if not mpg_rows:
        raise SystemExit(
            "No MPG games found in selected simulation window "
            f"(offset {args.event_offset}, limit {args.event_limit})."
        )
    probability_rows = compute_mpg_strategy.read_csv(args.probability_file)
    exact_score_rows = compute_mpg_strategy.read_csv(args.exact_score_file)
    completed_rows = compute_mpg_strategy.read_csv(args.completed_games_file)
    bettor_multipliers = compute_mpg_strategy.load_bettor_behavior_multipliers(
        args.bettor_multiplier_file
    )
    games, strategy_rows = build_games(
        mpg_rows,
        probability_rows,
        exact_score_rows,
        completed_rows,
        bettor_multipliers,
    )
    population, optimal = run_rollouts(games, args.rollouts, args.seed)
    progress_rows = summarize_progress(population, optimal)
    final_rows = final_rollout_rows(population, optimal)

    out_dir = Path(args.out_dir)
    progress_path = out_dir / "population_vs_optimal_progress.csv"
    write_csv(progress_path, progress_rows, PROGRESS_FIELDS)
    if args.write_rollouts:
        final_path = out_dir / "population_vs_optimal_final_rollouts.csv"
        write_csv(final_path, final_rows, FINAL_FIELDS)
    if args.write_plot:
        plot_path = out_dir / "population_vs_optimal_density.png"
        write_plot(plot_path, population, optimal)
        final_distribution_path = out_dir / "round3_points_distribution.png"
        write_final_distribution_plot(final_distribution_path, population, optimal)

    final = progress_rows[-1]
    crowd_final = population[:, -1]
    strategy_final = optimal[:, -1]
    optimal_wins = float(np.mean(strategy_final > crowd_final))
    population_wins = float(np.mean(strategy_final < crowd_final))
    ties = float(np.mean(strategy_final == crowd_final))
    print(f"Games simulated: {len(games)}")
    print(f"Simulation window: offset {args.event_offset}, limit {args.event_limit or 'all remaining'}")
    print(f"Completed games resolved from results: {sum(game.actual_outcome is not None for game in games)}")
    print(f"Rollouts: {args.rollouts} (seed={args.seed})")
    print(f"EV-optimal decisions evaluated: {len(strategy_rows)}")
    print(f"Final population mean points: {float(final['population_mean_points']):.2f}")
    print(f"Final optimal mean points: {float(final['optimal_mean_points']):.2f}")
    print(f"Final mean optimal edge: {float(final['optimal_mean_edge']):.2f}")
    print(f"Optimal ahead / population ahead / tied: {optimal_wins:.1%} / {population_wins:.1%} / {ties:.1%}")
    print(f"Saved progress summary: {progress_path}")
    if args.write_rollouts:
        print(f"Saved final rollouts: {final_path}")
    if args.write_plot:
        print(f"Saved density plot: {plot_path}")
        print(f"Saved final distribution plot: {final_distribution_path}")


if __name__ == "__main__":
    main()
