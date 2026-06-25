#!/usr/bin/env python3
"""Plot 1X2 outcome calibration for Premier League 2025-26 results."""

from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "data/analysis/calibration/historical/prem_2025.csv"
DEFAULT_OUT_DIR = ROOT / "data/analysis/calibration/historical"
DEFAULT_PLOT = DEFAULT_OUT_DIR / "premier_league_2025_outcome_calibration.png"
DEFAULT_SUMMARY = DEFAULT_OUT_DIR / "premier_league_2025_outcome_calibration.csv"
DEFAULT_RECORDS = DEFAULT_OUT_DIR / "premier_league_2025_outcome_calibration_records.csv"


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def write_csv(path: str | Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_float(value: str) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def vig_free_probabilities(home_odds: float, draw_odds: float, away_odds: float) -> dict[str, float]:
    raw = {
        "H": 1.0 / home_odds,
        "D": 1.0 / draw_odds,
        "A": 1.0 / away_odds,
    }
    total = sum(raw.values())
    return {outcome: probability / total for outcome, probability in raw.items()}


def wilson_interval(hits: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = hits / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def build_records(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for row in rows:
        odds = [
            parse_float(row.get("AvgCH", "")),
            parse_float(row.get("AvgCD", "")),
            parse_float(row.get("AvgCA", "")),
        ]
        if any(value is None for value in odds) or row.get("FTR") not in {"H", "D", "A"}:
            continue
        probabilities = vig_free_probabilities(odds[0], odds[1], odds[2])  # type: ignore[arg-type]
        match = f"{row['HomeTeam']} vs {row['AwayTeam']}"
        for outcome, probability in probabilities.items():
            records.append(
                {
                    "date": row["Date"],
                    "match": match,
                    "outcome": outcome,
                    "actual_outcome": row["FTR"],
                    "predicted_probability": probability,
                    "hit": int(row["FTR"] == outcome),
                }
            )
    return records


def summarize_bins(records: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for index in range(10):
        low = index / 10
        high = (index + 1) / 10
        in_bin = [
            row
            for row in records
            if low <= float(row["predicted_probability"]) < high
            or (high == 1.0 and low <= float(row["predicted_probability"]) <= high)
        ]
        if not in_bin:
            continue
        n = len(in_bin)
        hits = sum(int(row["hit"]) for row in in_bin)
        observed = hits / n
        average = sum(float(row["predicted_probability"]) for row in in_bin) / n
        wilson_low, wilson_high = wilson_interval(hits, n)
        summaries.append(
            {
                "bin": f"{int(low * 100)}-{int(high * 100)}",
                "bin_low": low,
                "bin_high": high,
                "n": n,
                "hits": hits,
                "avg_predicted_probability": average,
                "observed_hit_rate": observed,
                "wilson_low": wilson_low,
                "wilson_high": wilson_high,
            }
        )
    return summaries


def plot(path: str | Path, summaries: list[dict[str, object]], match_count: int) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpp-matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [100 * float(row["avg_predicted_probability"]) for row in summaries]
    ys = [100 * float(row["observed_hit_rate"]) for row in summaries]
    yerr = [
        [100 * (float(row["observed_hit_rate"]) - float(row["wilson_low"])) for row in summaries],
        [100 * (float(row["wilson_high"]) - float(row["observed_hit_rate"])) for row in summaries],
    ]

    fig, ax = plt.subplots(figsize=(8, 7))
    ax.plot([0, 100], [0, 100], color="#555555", linestyle="--", linewidth=1.8, label="Perfect calibration")
    ax.errorbar(
        xs,
        ys,
        yerr=yerr,
        marker="o",
        color="#1f77b4",
        linewidth=2,
        capsize=4,
        label="Observed outcome rate",
    )
    for x, y, row in zip(xs, ys, summaries):
        ax.annotate(
            f"n={row['n']}\n{row['hits']}/{row['n']}",
            xy=(x, y),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color="#333333",
        )
    ax.set_title("Premier League 2025-26 outcome calibration")
    ax.set_xlabel("Average vig-free closing probability (%)")
    ax.set_ylabel("Outcome occurred (%)")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.grid(color="#dddddd", linewidth=0.8)
    ax.legend(loc="upper left")
    fig.text(
        0.01,
        0.01,
        f"Resolved matches={match_count} | outcome rows={match_count * 3} | "
        "Avg closing odds vig-removed; error bars are 95% Wilson intervals",
        fontsize=9,
        color="#444444",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    records = build_records(read_csv(args.input))
    summaries = summarize_bins(records)
    summary_fields = [
        "bin",
        "bin_low",
        "bin_high",
        "n",
        "hits",
        "avg_predicted_probability",
        "observed_hit_rate",
        "wilson_low",
        "wilson_high",
    ]
    write_csv(out_dir / DEFAULT_RECORDS.name, records, ["date", "match", "outcome", "actual_outcome", "predicted_probability", "hit"])
    write_csv(out_dir / DEFAULT_SUMMARY.name, summaries, summary_fields)
    plot_path = out_dir / DEFAULT_PLOT.name
    plot(plot_path, summaries, len(records) // 3)
    print(f"Matched games: {len(records) // 3}")
    print(f"Outcome records: {len(records)}")
    print(f"Saved plot: {plot_path}")


if __name__ == "__main__":
    main()
