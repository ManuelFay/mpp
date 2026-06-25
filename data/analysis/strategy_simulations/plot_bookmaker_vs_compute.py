#!/usr/bin/env python3
"""Plot bookmaker-injected and compute-optimal rollout distributions together."""

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


DEFAULT_BOOKMAKER_ROLLOUTS = (
    "data/analysis/strategy_simulations/bookmaker_injected/top1_total_rollouts.csv"
)
DEFAULT_COMPUTE_ROLLOUTS = (
    "data/analysis/strategy_simulations/optimal_bookmaker_injected_assessment/"
    "optimal_assessed_with_bookmaker_injected_rollouts.csv"
)
DEFAULT_BOOKMAKER_REALIZED = 1787.0
DEFAULT_COMPUTE_REALIZED = 1770.0
DEFAULT_OUT = (
    "data/analysis/strategy_simulations/optimal_bookmaker_injected_assessment/"
    "bookmaker_injected_vs_compute_optimal_distribution.png"
)
DEFAULT_BOOKMAKER_RESULTS = (
    "data/analysis/strategy_simulations/bookmaker_injected/completed_top1_results.csv"
)
DEFAULT_COMPUTE_RESULTS = (
    "data/analysis/strategy_simulations/optimal_bookmaker_injected_assessment/"
    "optimal_assessed_with_bookmaker_injected_results.csv"
)
DEFAULT_BOOKMAKER_PREDICTIONS = "data/bookmaker_injected/expected_mpg_top5.csv"
DEFAULT_COMPLETED_FILE = "data/mpg/completed_games.csv"
DEFAULT_MPG_FILE = "data/mpg/mpg.txt"
DEFAULT_ROLLOUTS = 200_000
DEFAULT_SEED = 20260625


def read_totals(path: str | Path) -> np.ndarray:
    with Path(path).open(newline="", encoding="utf-8") as file:
        return np.array(
            [float(row["total_points"]) for row in csv.DictReader(file)],
            dtype=float,
        )


def read_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def simulate_compute_subset(
    rows: list[dict[str, str]],
    rollouts: int,
    seed: int,
) -> np.ndarray:
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
            shares = rng.normal(
                float(row["bookmaker_conditional_bettor_share"]),
                0.01,
                size=exact_count,
            )
            bonus = np.select(
                [shares > 0.30, shares >= 0.20, shares >= 0.05, shares >= 0.005],
                [20.0, 30.0, 50.0, 70.0],
                default=100.0,
            )
            totals[exact] += base_points + bonus
    return totals


def day_slices(length: int) -> list[tuple[str, slice]]:
    if length < 48:
        raise ValueError(f"Expected at least 48 resolved games, found {length}")
    return [("Match day 1", slice(0, 24)), ("Match day 2", slice(24, 48))]


def plot_distribution(
    bookmaker_totals: np.ndarray,
    compute_totals: np.ndarray,
    bookmaker_realized: float,
    compute_realized: float,
    out_path: Path,
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpp-matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 7))
    bins = np.linspace(
        min(bookmaker_totals.min(), compute_totals.min()),
        max(bookmaker_totals.max(), compute_totals.max()),
        56,
    )
    series = [
        (
            "Bookmaker-injected top 1",
            bookmaker_totals,
            bookmaker_realized,
            "#7c3aed",
            "#4c1d95",
        ),
        (
            "Compute MPG optimal",
            compute_totals,
            compute_realized,
            "#0891b2",
            "#155e75",
        ),
    ]
    for label, totals, realized, color, marker_color in series:
        mean = float(totals.mean())
        percentile = float(np.mean(totals <= realized))
        ax.hist(
            totals,
            bins=bins,
            density=True,
            alpha=0.32,
            color=color,
            edgecolor="none",
            label=f"{label} distribution",
        )
        ax.hist(
            totals,
            bins=bins,
            density=True,
            histtype="step",
            linewidth=2.4,
            color=color,
        )
        ax.axvline(
            mean,
            color=color,
            linestyle="--",
            linewidth=2.0,
            label=f"{label} mean: {mean:.0f}",
        )
        ax.axvline(
            realized,
            color=marker_color,
            linewidth=2.8,
            label=f"{label} realized: {realized:.0f} ({percentile:.1%})",
        )

    ax.set_title(
        "Bookmaker-Injected vs Compute MPG Strategy",
        fontsize=16,
        fontweight="bold",
        pad=14,
    )
    ax.set_xlabel("Total points over 48 resolved games", fontsize=12)
    ax.set_ylabel("Probability density", fontsize=12)
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
        fontsize=10,
    )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def plot_match_day_distributions(
    bookmaker_picks: list[bookmaker_results.ScoredPick],
    compute_rows: list[dict[str, str]],
    rollouts: int,
    seed: int,
    out_path: Path,
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpp-matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 1, figsize=(12, 14), sharex=False)
    colors = {
        "bookmaker": ("#7c3aed", "#4c1d95"),
        "compute": ("#0891b2", "#155e75"),
    }
    panels = day_slices(len(compute_rows)) + [("Total", slice(0, 48))]
    for index, (title, day_slice) in enumerate(panels):
        ax = axes[index]
        bookmaker_subset = bookmaker_picks[day_slice]
        compute_subset = compute_rows[day_slice]
        bookmaker_totals = bookmaker_results.simulate_totals(
            bookmaker_subset,
            rollouts,
            seed + index * 2,
        )
        compute_totals = simulate_compute_subset(
            compute_subset,
            rollouts,
            seed + index * 2 + 1,
        )
        bookmaker_realized = sum(pick.realized_points for pick in bookmaker_subset)
        compute_realized = sum(float(row["realized_points"]) for row in compute_subset)
        bins = np.linspace(
            min(bookmaker_totals.min(), compute_totals.min()),
            max(bookmaker_totals.max(), compute_totals.max()),
            46,
        )

        series = [
            (
                "Bookmaker-injected top 1",
                bookmaker_totals,
                bookmaker_realized,
                colors["bookmaker"][0],
                colors["bookmaker"][1],
            ),
            (
                "Compute MPG optimal",
                compute_totals,
                compute_realized,
                colors["compute"][0],
                colors["compute"][1],
            ),
        ]
        for label, totals, realized, color, marker_color in series:
            mean = float(totals.mean())
            percentile = float(np.mean(totals <= realized))
            ax.hist(
                totals,
                bins=bins,
                density=True,
                alpha=0.32,
                color=color,
                edgecolor="none",
                label=f"{label} dist.",
            )
            ax.hist(
                totals,
                bins=bins,
                density=True,
                histtype="step",
                linewidth=2.2,
                color=color,
            )
            ax.axvline(
                mean,
                color=color,
                linestyle="--",
                linewidth=1.8,
                label=f"{label} mean {mean:.0f}",
            )
            ax.axvline(
                realized,
                color=marker_color,
                linewidth=2.5,
                label=f"{label} realized {realized:.0f} ({percentile:.1%})",
            )

        ax.set_title(title, fontsize=14, fontweight="bold", loc="left")
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
            fontsize=8.5,
            loc="upper right",
            ncol=2,
        )
    axes[-1].set_xlabel("Total points")
    fig.suptitle(
        "Bookmaker-Injected vs Compute MPG Strategy by Match Day",
        fontsize=16,
        fontweight="bold",
        y=0.98,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bookmaker-rollouts", default=DEFAULT_BOOKMAKER_ROLLOUTS)
    parser.add_argument("--compute-rollouts", default=DEFAULT_COMPUTE_ROLLOUTS)
    parser.add_argument("--bookmaker-realized", type=float, default=DEFAULT_BOOKMAKER_REALIZED)
    parser.add_argument("--compute-realized", type=float, default=DEFAULT_COMPUTE_REALIZED)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--bookmaker-results", default=DEFAULT_BOOKMAKER_RESULTS)
    parser.add_argument("--compute-results", default=DEFAULT_COMPUTE_RESULTS)
    parser.add_argument("--bookmaker-predictions", default=DEFAULT_BOOKMAKER_PREDICTIONS)
    parser.add_argument("--completed-file", default=DEFAULT_COMPLETED_FILE)
    parser.add_argument("--mpg-file", default=DEFAULT_MPG_FILE)
    parser.add_argument("--rollouts", type=int, default=DEFAULT_ROLLOUTS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--combined-total",
        action="store_true",
        help="Plot one combined 48-game distribution instead of match-day subplots.",
    )
    args = parser.parse_args()

    if args.combined_total:
        plot_distribution(
            read_totals(args.bookmaker_rollouts),
            read_totals(args.compute_rollouts),
            args.bookmaker_realized,
            args.compute_realized,
            Path(args.out),
        )
    else:
        bookmaker_picks = bookmaker_results.score_completed_picks(
            read_rows(args.bookmaker_predictions),
            read_rows(args.completed_file),
            read_rows(args.mpg_file),
        )
        compute_rows = sorted(
            read_rows(args.compute_results),
            key=lambda row: row["commence_time"],
        )
        plot_match_day_distributions(
            bookmaker_picks,
            compute_rows,
            args.rollouts,
            args.seed,
            Path(args.out),
        )
    print(f"Saved plot: {args.out}")


if __name__ == "__main__":
    main()
