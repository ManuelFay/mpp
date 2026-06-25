#!/usr/bin/env python3
"""Simulate bookmaker-injected top picks on completed games and plot points."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SIMULATION_DIR = ROOT / "data" / "analysis" / "strategy_simulations"
if str(SIMULATION_DIR) not in sys.path:
    sys.path.insert(0, str(SIMULATION_DIR))

import analyze_bookmaker_injected_results as bookmaker_simulation


DEFAULT_OUT_DIR = Path("data/analysis/strategy_simulations/bookmaker_injected")
DEFAULT_PLOT = DEFAULT_OUT_DIR / "top1_luck_distribution.png"
DEFAULT_ROLLOUTS = 200_000
DEFAULT_SEED = 20260615


def main() -> None:
    picks = bookmaker_simulation.score_completed_picks(
        bookmaker_simulation.read_csv(bookmaker_simulation.DEFAULT_PREDICTION_FILE),
        bookmaker_simulation.read_csv(bookmaker_simulation.DEFAULT_COMPLETED_FILE),
        bookmaker_simulation.read_csv(bookmaker_simulation.DEFAULT_MPG_FILE),
    )
    if not picks:
        raise SystemExit("No completed games matched bookmaker-injected top-1 picks")

    totals = bookmaker_simulation.simulate_totals(
        picks,
        rollouts=DEFAULT_ROLLOUTS,
        seed=DEFAULT_SEED,
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


if __name__ == "__main__":
    main()
