#!/usr/bin/env python3
"""
Analyze odds movements between timestamped snapshot CSVs.

The script compares matching rows across consecutive snapshots using:

  event_id + bookmaker_key + market + outcome + point

Outputs:
  data/analysis/odds_changes.csv
  data/analysis/odds_changes_top.csv
  data/analysis/odds_changes_top_implied_probability.csv
  data/analysis/odds_changes_summary.csv
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

from odds_pipeline import filters


DEFAULT_SNAPSHOT_DIR = "data/odds_snapshots"
DEFAULT_SNAPSHOT_PREFIX = "world_cup_first_round_odds"
DEFAULT_OUT = "data/analysis/odds_changes.csv"
DEFAULT_TOP_OUT = "data/analysis/odds_changes_top.csv"
DEFAULT_TOP_PROBABILITY_OUT = "data/analysis/odds_changes_top_implied_probability.csv"
DEFAULT_SUMMARY_OUT = "data/analysis/odds_changes_summary.csv"
DEFAULT_TOP_N = 100

TIMESTAMP_RE = re.compile(r"_(\d{8}T\d{6}Z)\.csv$")

CHANGE_FIELDS = [
    "from_snapshot",
    "to_snapshot",
    "from_timestamp",
    "to_timestamp",
    "event_id",
    "commence_time",
    "home_team",
    "away_team",
    "bookmaker_key",
    "bookmaker",
    "market",
    "outcome",
    "point",
    "from_price",
    "to_price",
    "price_change",
    "abs_price_change",
    "price_pct_change",
    "from_implied_probability",
    "to_implied_probability",
    "implied_probability_change",
    "abs_implied_probability_change",
]

SUMMARY_FIELDS = [
    "from_snapshot",
    "to_snapshot",
    "from_timestamp",
    "to_timestamp",
    "from_rows",
    "to_rows",
    "matched_rows",
    "new_rows",
    "removed_rows",
    "changed_rows",
    "max_abs_price_change",
    "max_abs_implied_probability_change",
]


@dataclass(frozen=True)
class Snapshot:
    path: Path
    timestamp: str


def snapshot_timestamp(path: Path) -> str | None:
    match = TIMESTAMP_RE.search(path.name)
    if not match:
        return None
    return match.group(1)


def find_snapshots(snapshot_dir: str | Path, snapshot_prefix: str) -> list[Snapshot]:
    root = Path(snapshot_dir)
    snapshots = []
    for path in root.rglob("*.csv"):
        if path.name == "latest.csv":
            continue
        timestamp = snapshot_timestamp(path)
        if timestamp is None:
            continue
        if path.name != f"{snapshot_prefix}_{timestamp}.csv":
            continue
        snapshots.append(Snapshot(path=path, timestamp=timestamp))
    return sorted(snapshots, key=lambda snapshot: snapshot.timestamp)


def normalized_point(value: str) -> str:
    if value == "":
        return ""
    return str(float(value))


def row_key(row: dict[str, str]) -> tuple[str, str, str, str, str]:
    return (
        row["event_id"],
        row["bookmaker_key"],
        row["market"],
        row["outcome"],
        normalized_point(row["point"]),
    )


def read_snapshot(snapshot: Snapshot) -> dict[tuple[str, str, str, str, str], dict[str, str]]:
    with snapshot.path.open(newline="", encoding="utf-8") as f:
        snapshot_rows = filters.filter_snapshot_rows(list(csv.DictReader(f)))

    rows: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    for row in snapshot_rows:
        if not row.get("price"):
            continue
        rows[row_key(row)] = row
    return rows


def compare_pair(
    previous: Snapshot,
    current: Snapshot,
) -> tuple[list[dict[str, str | float]], dict[str, str | int | float]]:
    previous_rows = read_snapshot(previous)
    current_rows = read_snapshot(current)
    previous_keys = set(previous_rows)
    current_keys = set(current_rows)
    matched_keys = sorted(previous_keys & current_keys)

    changes: list[dict[str, str | float]] = []
    for key in matched_keys:
        old = previous_rows[key]
        new = current_rows[key]
        from_price = float(old["price"])
        to_price = float(new["price"])
        price_change = to_price - from_price
        implied_change = (1 / to_price) - (1 / from_price)

        if price_change == 0:
            continue

        changes.append(
            {
                "from_snapshot": str(previous.path),
                "to_snapshot": str(current.path),
                "from_timestamp": previous.timestamp,
                "to_timestamp": current.timestamp,
                "event_id": new["event_id"],
                "commence_time": new["commence_time"],
                "home_team": new["home_team"],
                "away_team": new["away_team"],
                "bookmaker_key": new["bookmaker_key"],
                "bookmaker": new["bookmaker"],
                "market": new["market"],
                "outcome": new["outcome"],
                "point": normalized_point(new["point"]),
                "from_price": from_price,
                "to_price": to_price,
                "price_change": price_change,
                "abs_price_change": abs(price_change),
                "price_pct_change": price_change / from_price,
                "from_implied_probability": 1 / from_price,
                "to_implied_probability": 1 / to_price,
                "implied_probability_change": implied_change,
                "abs_implied_probability_change": abs(implied_change),
            }
        )

    summary = {
        "from_snapshot": str(previous.path),
        "to_snapshot": str(current.path),
        "from_timestamp": previous.timestamp,
        "to_timestamp": current.timestamp,
        "from_rows": len(previous_rows),
        "to_rows": len(current_rows),
        "matched_rows": len(matched_keys),
        "new_rows": len(current_keys - previous_keys),
        "removed_rows": len(previous_keys - current_keys),
        "changed_rows": len(changes),
        "max_abs_price_change": max((float(row["abs_price_change"]) for row in changes), default=0.0),
        "max_abs_implied_probability_change": max(
            (float(row["abs_implied_probability_change"]) for row in changes),
            default=0.0,
        ),
    }
    return changes, summary


def write_csv(rows: list[dict[str, str | int | float]], path: str | Path, fields: list[str]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument(
        "--snapshot-prefix",
        default=DEFAULT_SNAPSHOT_PREFIX,
        help="Only analyze timestamped CSVs in this exact filename series.",
    )
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--top-out", default=DEFAULT_TOP_OUT)
    parser.add_argument("--top-probability-out", default=DEFAULT_TOP_PROBABILITY_OUT)
    parser.add_argument("--summary-out", default=DEFAULT_SUMMARY_OUT)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    args = parser.parse_args()

    snapshots = find_snapshots(args.snapshot_dir, args.snapshot_prefix)
    if len(snapshots) < 2:
        raise SystemExit(f"Need at least two timestamped snapshots in {args.snapshot_dir}; found {len(snapshots)}.")

    all_changes: list[dict[str, str | float]] = []
    summaries: list[dict[str, str | int | float]] = []
    for previous, current in zip(snapshots, snapshots[1:]):
        changes, summary = compare_pair(previous, current)
        all_changes.extend(changes)
        summaries.append(summary)

    all_changes.sort(key=lambda row: float(row["abs_price_change"]), reverse=True)
    top_changes = all_changes[: args.top_n]
    top_probability_changes = sorted(
        all_changes,
        key=lambda row: float(row["abs_implied_probability_change"]),
        reverse=True,
    )[: args.top_n]

    write_csv(all_changes, args.out, CHANGE_FIELDS)
    write_csv(top_changes, args.top_out, CHANGE_FIELDS)
    write_csv(top_probability_changes, args.top_probability_out, CHANGE_FIELDS)
    write_csv(summaries, args.summary_out, SUMMARY_FIELDS)

    print(f"Snapshots analyzed: {len(snapshots)}")
    print(f"Intervals compared: {len(summaries)}")
    print(f"Changed odds rows: {len(all_changes)}")
    print(f"Saved all changes: {args.out}")
    print(f"Saved top changes: {args.top_out}")
    print(f"Saved top implied-probability changes: {args.top_probability_out}")
    print(f"Saved summary: {args.summary_out}")

    if top_changes:
        biggest = top_changes[0]
        print(
            "Biggest raw odds move: "
            f"{biggest['home_team']} vs {biggest['away_team']} | "
            f"{biggest['bookmaker']} {biggest['market']} {biggest['outcome']} "
            f"{biggest['point']} | {biggest['from_price']} -> {biggest['to_price']} "
            f"({float(biggest['price_change']):+.2f})"
        )
    if top_probability_changes:
        biggest_probability = top_probability_changes[0]
        print(
            "Biggest implied-probability move: "
            f"{biggest_probability['home_team']} vs {biggest_probability['away_team']} | "
            f"{biggest_probability['bookmaker']} {biggest_probability['market']} "
            f"{biggest_probability['outcome']} {biggest_probability['point']} | "
            f"{biggest_probability['from_implied_probability']:.4f} -> "
            f"{biggest_probability['to_implied_probability']:.4f} "
            f"({float(biggest_probability['implied_probability_change']):+.4f})"
        )


if __name__ == "__main__":
    main()
