#!/usr/bin/env python3
"""Compare simple odds-to-probability conversions on all-Europe outcome data."""

from __future__ import annotations

import csv
import math
import os
from pathlib import Path

from plot_all_euro_2025_calibration import (
    DEFAULT_OUT_DIR,
    build_records,
    read_workbook,
    summarize_bins,
)


ROOT = Path(__file__).resolve().parents[3]
SEASONS = [
    (
        "2024-25",
        ROOT / "data/analysis/calibration/historical/all-euro-data-2024-2025.xlsx",
    ),
    (
        "2025-26",
        ROOT / "data/analysis/calibration/historical/all-euro-data-2025-2026.xlsx",
    ),
]
METHODS = [
    ("proportional", "#1f77b4", "Proportional"),
    ("power", "#ff7f0e", "Power"),
]


def write_csv(path: str | Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def calibration_error(summaries: list[dict[str, object]]) -> float:
    total = sum(int(row["n"]) for row in summaries)
    if total == 0:
        return 0.0
    return sum(
        int(row["n"])
        * abs(float(row["observed_hit_rate"]) - float(row["avg_predicted_probability"]))
        for row in summaries
    ) / total


def score_records(
    records: list[dict[str, object]],
    summaries: list[dict[str, object]],
) -> dict[str, float]:
    brier = sum(
        (float(row["predicted_probability"]) - int(row["hit"])) ** 2
        for row in records
    ) / len(records)
    actual_probabilities = [
        max(float(row["predicted_probability"]), 1e-15)
        for row in records
        if int(row["hit"]) == 1
    ]
    log_loss = -sum(math.log(probability) for probability in actual_probabilities) / len(
        actual_probabilities
    )
    high_85 = [
        row
        for row in records
        if float(row["predicted_probability"]) >= 0.85
    ]
    high_90 = [
        row
        for row in records
        if float(row["predicted_probability"]) >= 0.90
    ]

    def observed(rows: list[dict[str, object]]) -> float:
        if not rows:
            return 0.0
        return sum(int(row["hit"]) for row in rows) / len(rows)

    def average_probability(rows: list[dict[str, object]]) -> float:
        if not rows:
            return 0.0
        return sum(float(row["predicted_probability"]) for row in rows) / len(rows)

    return {
        "brier": brier,
        "log_loss": log_loss,
        "ece_10bin": calibration_error(summaries),
        "tail85_n": len(high_85),
        "tail85_avg_predicted_probability": average_probability(high_85),
        "tail85_observed_hit_rate": observed(high_85),
        "tail90_n": len(high_90),
        "tail90_avg_predicted_probability": average_probability(high_90),
        "tail90_observed_hit_rate": observed(high_90),
    }


def plot_comparison(
    path: str | Path,
    season_results: list[dict[str, object]],
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpp-matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(
        1,
        len(season_results),
        figsize=(15, 6.4),
        sharex=True,
        sharey=True,
    )
    if len(season_results) == 1:
        axes = [axes]

    for ax, season_result in zip(axes, season_results):
        ax.plot([0, 100], [0, 100], color="#555555", linestyle="--", linewidth=1.5, label="Perfect")
        for method, color, label in METHODS:
            summaries = season_result["summaries"][method]
            metrics = season_result["metrics"][method]
            xs = [100 * float(row["avg_predicted_probability"]) for row in summaries]
            ys = [100 * float(row["observed_hit_rate"]) for row in summaries]
            yerr = [
                [100 * (float(row["observed_hit_rate"]) - float(row["wilson_low"])) for row in summaries],
                [100 * (float(row["wilson_high"]) - float(row["observed_hit_rate"])) for row in summaries],
            ]
            ax.errorbar(
                xs,
                ys,
                yerr=yerr,
                marker="o",
                linewidth=2,
                markersize=5,
                capsize=3,
                color=color,
                label=f"{label} | BS {metrics['brier']:.4f}, LL {metrics['log_loss']:.4f}",
            )
        ax.set_title(f"All Europe {season_result['season']}")
        ax.set_xlabel("Average vig-free 1X2 probability (%)")
        ax.grid(color="#dddddd", linewidth=0.8)
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.legend(loc="upper left", fontsize=8)
        ax.text(
            0.02,
            0.03,
            f"matches={season_result['matches']:,}",
            transform=ax.transAxes,
            fontsize=9,
            color="#444444",
        )

    axes[0].set_ylabel("Outcome occurred (%)")
    fig.suptitle("Outcome calibration by odds-to-probability conversion", y=0.98)
    fig.text(
        0.01,
        0.01,
        "BS=Brier score over outcome rows, LL=per-match log loss. Lower is better.",
        fontsize=9,
        color="#444444",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=180)
    plt.close(fig)


def main() -> None:
    metric_rows: list[dict[str, object]] = []
    season_results: list[dict[str, object]] = []

    for season, workbook in SEASONS:
        rows = read_workbook(workbook)
        summaries_by_method: dict[str, list[dict[str, object]]] = {}
        metrics_by_method: dict[str, dict[str, float]] = {}
        matches = 0
        for method, _, _ in METHODS:
            records = build_records(rows, method=method)
            summaries = summarize_bins(records)
            metrics = score_records(records, summaries)
            summaries_by_method[method] = summaries
            metrics_by_method[method] = metrics
            matches = len(records) // 3
            metric_rows.append(
                {
                    "season": season,
                    "method": method,
                    "matches": matches,
                    "outcome_rows": len(records),
                    "brier": metrics["brier"],
                    "log_loss": metrics["log_loss"],
                    "ece_10bin": metrics["ece_10bin"],
                    "tail85_n": metrics["tail85_n"],
                    "tail85_avg_predicted_probability": metrics["tail85_avg_predicted_probability"],
                    "tail85_observed_hit_rate": metrics["tail85_observed_hit_rate"],
                    "tail90_n": metrics["tail90_n"],
                    "tail90_avg_predicted_probability": metrics["tail90_avg_predicted_probability"],
                    "tail90_observed_hit_rate": metrics["tail90_observed_hit_rate"],
                }
            )
        season_results.append(
            {
                "season": season,
                "matches": matches,
                "summaries": summaries_by_method,
                "metrics": metrics_by_method,
            }
        )

    out_dir = Path(DEFAULT_OUT_DIR)
    metrics_path = out_dir / "all_euro_devig_method_comparison_metrics.csv"
    write_csv(
        metrics_path,
        metric_rows,
        [
            "season",
            "method",
            "matches",
            "outcome_rows",
            "brier",
            "log_loss",
            "ece_10bin",
            "tail85_n",
            "tail85_avg_predicted_probability",
            "tail85_observed_hit_rate",
            "tail90_n",
            "tail90_avg_predicted_probability",
            "tail90_observed_hit_rate",
        ],
    )
    plot_path = out_dir / "all_euro_devig_method_comparison.png"
    plot_comparison(plot_path, season_results)
    print(f"Saved metrics: {metrics_path}")
    print(f"Saved plot: {plot_path}")


if __name__ == "__main__":
    main()
