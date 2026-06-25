#!/usr/bin/env python3
"""Simulate bookmaker-injected top picks on completed games and plot points."""

from __future__ import annotations

import sys
import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SIMULATION_DIR = ROOT / "data" / "analysis" / "strategy_simulations"
if str(SIMULATION_DIR) not in sys.path:
    sys.path.insert(0, str(SIMULATION_DIR))

import analyze_bookmaker_injected_results as bookmaker_simulation


DEFAULT_OUT_DIR = Path("data/analysis/strategy_simulations/bookmaker_injected")
DEFAULT_PLOT = DEFAULT_OUT_DIR / "top1_luck_distribution.png"
DEFAULT_COMPARISON_PLOT = DEFAULT_OUT_DIR / "top1_vs_random_player_distribution.png"
DEFAULT_RANDOM_RESOLVED_PLOT = DEFAULT_OUT_DIR / "random_player_resolved_points_distribution.png"
DEFAULT_ROLLOUTS = 200_000
DEFAULT_SEED = 20260615


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--include-random-player",
        action="store_true",
        help=(
            "Also simulate a random MPG player who samples exact-score picks "
            "proportionally to displayed bettor shares."
        ),
    )
    parser.add_argument("--rollouts", type=int, default=DEFAULT_ROLLOUTS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    if args.rollouts <= 0:
        raise SystemExit("--rollouts must be positive")

    prediction_rows = bookmaker_simulation.read_csv(
        bookmaker_simulation.DEFAULT_PREDICTION_FILE
    )
    completed_rows = bookmaker_simulation.read_csv(
        bookmaker_simulation.DEFAULT_COMPLETED_FILE
    )
    mpg_rows = bookmaker_simulation.read_csv(bookmaker_simulation.DEFAULT_MPG_FILE)
    picks = bookmaker_simulation.score_completed_picks(
        prediction_rows,
        completed_rows,
        mpg_rows,
    )
    if not picks:
        raise SystemExit("No completed games matched bookmaker-injected top-1 picks")

    totals = bookmaker_simulation.simulate_totals(
        picks,
        rollouts=args.rollouts,
        seed=args.seed,
    )
    realized = sum(pick.realized_points for pick in picks)
    expected = sum(pick.expected_points for pick in picks)
    mean = float(totals.mean())
    sigma = float(totals.std())
    percentile = float((totals <= realized).mean())

    DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    bookmaker_simulation.write_csv(
        DEFAULT_OUT_DIR / "completed_top1_results.csv",
        bookmaker_simulation.result_rows(picks),
        bookmaker_simulation.RESULT_FIELDS,
    )
    bookmaker_simulation.write_plot(DEFAULT_PLOT, totals, realized)

    print(f"Completed bookmaker-injected top-1 picks: {len(picks)}")
    print(f"Resolved points: {realized:.2f}")
    print(f"Logged expected value: {expected:.2f}")
    print(f"Resolved minus EV: {realized - expected:+.2f}")
    print(f"Simulation mean / standard deviation: {mean:.2f} / {sigma:.2f}")
    print(f"Resolved percentile: {percentile:.2%}")
    print(f"Saved plot: {DEFAULT_PLOT}")
    print(f"Saved per-game results: {DEFAULT_OUT_DIR / 'completed_top1_results.csv'}")

    if args.include_random_player:
        random_games = bookmaker_simulation.score_random_player_games(
            prediction_rows,
            bookmaker_simulation.read_csv(bookmaker_simulation.DEFAULT_ODDS_LOG_FILE),
            completed_rows,
            mpg_rows,
        )
        if not random_games:
            raise SystemExit("No completed games matched random-player bookmaker rows")
        random_totals = bookmaker_simulation.simulate_random_player_totals(
            random_games,
            rollouts=args.rollouts,
            seed=args.seed + 1,
        )
        random_resolved_totals = (
            bookmaker_simulation.simulate_random_player_resolved_totals(
                random_games,
                players=args.rollouts,
                seed=args.seed + 2,
            )
        )
        random_realized = bookmaker_simulation.random_player_realized_points(random_games)
        random_expected = bookmaker_simulation.random_player_expected_points(random_games)
        random_mean = float(random_totals.mean())
        random_sigma = float(random_totals.std())
        random_percentile = float((random_totals <= random_realized).mean())
        random_resolved_mean = float(random_resolved_totals.mean())
        random_resolved_sigma = float(random_resolved_totals.std())
        bookmaker_vs_random_resolved_percentile = float(
            (random_resolved_totals <= realized).mean()
        )

        difference_totals = totals - random_totals
        difference_realized = realized - random_realized
        difference_mean = float(difference_totals.mean())
        difference_sigma = float(difference_totals.std())
        difference_percentile = float(
            (difference_totals <= difference_realized).mean()
        )

        bookmaker_simulation.write_comparison_plot(
            DEFAULT_COMPARISON_PLOT,
            totals,
            realized,
            random_totals,
            random_realized,
            difference_totals,
            difference_realized,
        )
        bookmaker_simulation.write_resolved_random_player_plot(
            DEFAULT_RANDOM_RESOLVED_PLOT,
            random_resolved_totals,
            realized,
        )

        print("")
        print(f"Completed random MPG player games: {len(random_games)}")
        print(f"Random resolved expected points: {random_realized:.2f}")
        print(f"Random expected value: {random_expected:.2f}")
        print(
            "Random simulation mean / standard deviation: "
            f"{random_mean:.2f} / {random_sigma:.2f}"
        )
        print(f"Random resolved percentile: {random_percentile:.2%}")
        print("")
        print("Difference: bookmaker-injected top-1 minus random MPG player")
        print(f"Resolved difference: {difference_realized:+.2f}")
        print(f"Expected mean difference: {difference_mean:+.2f}")
        print(
            "Difference simulation mean / standard deviation: "
            f"{difference_mean:.2f} / {difference_sigma:.2f}"
        )
        print(f"Resolved difference percentile: {difference_percentile:.2%}")
        print(f"Saved comparison plot: {DEFAULT_COMPARISON_PLOT}")
        print("")
        print("Resolved games: sampled random players by bettor share")
        print(
            "Random-player realized mean / standard deviation: "
            f"{random_resolved_mean:.2f} / {random_resolved_sigma:.2f}"
        )
        print(
            "Bookmaker-injected top-1 percentile vs random players: "
            f"{bookmaker_vs_random_resolved_percentile:.2%}"
        )
        print(f"Saved resolved random-player plot: {DEFAULT_RANDOM_RESOLVED_PLOT}")


if __name__ == "__main__":
    main()
