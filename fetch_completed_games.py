#!/usr/bin/env python3
"""Fetch completed World Cup scores and merge them into MPG results."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

import compute_mpg_strategy
import fetch_odds


DEFAULT_SPORT_KEY = "soccer_fifa_world_cup"
DEFAULT_DAYS_FROM = 7
DEFAULT_COMPLETED_FILE = "data/mpg/completed_games.csv"
DEFAULT_MPG_FILE = compute_mpg_strategy.DEFAULT_MPG_FILE
DEFAULT_STRATEGY_FILE = compute_mpg_strategy.DEFAULT_OUT
DEFAULT_SCORE_EV_FILE = compute_mpg_strategy.DEFAULT_SCORE_EV_OUT

FIELDS = [
    "event_id",
    "commence_time",
    "home_team",
    "away_team",
    "home_score",
    "away_score",
    "final_score",
    "optimal_pick",
    "optimal_exact_score",
    "outcome_correct",
    "exact_score_correct",
    "base_points",
    "actual_exact_bonus_points",
    "total_points",
    "api_last_update",
]


def read_csv(path: str | Path) -> list[dict[str, str]]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_csv(path: str | Path, rows: list[dict[str, object]]) -> None:
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def score_by_team(event: dict[str, Any], team: str) -> int:
    scores = event.get("scores") or []
    for row in scores:
        if row.get("name") == team:
            return int(row["score"])
    raise ValueError(f"No score found for {team!r} in event {event.get('id')}")


def outcome_for_pick(pick: str, home_team: str, away_team: str) -> str:
    normalized_pick = compute_mpg_strategy.normalize_team(pick)
    if normalized_pick == compute_mpg_strategy.normalize_team(home_team):
        return "home"
    if normalized_pick == compute_mpg_strategy.normalize_team(away_team):
        return "away"
    if pick == "Draw":
        return "draw"
    raise ValueError(f"Cannot map optimal pick {pick!r} for {home_team} vs {away_team}")


def strategy_lookup(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {
        (
            compute_mpg_strategy.normalize_team(row["matched_home_team"]),
            compute_mpg_strategy.normalize_team(row["matched_away_team"]),
        ): row
        for row in rows
    }


def score_ev_lookup(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], dict[str, str]]:
    return {
        (
            compute_mpg_strategy.normalize_team(row["matched_home_team"]),
            compute_mpg_strategy.normalize_team(row["matched_away_team"]),
            row["score"],
        ): row
        for row in rows
    }


def completed_row(
    event: dict[str, Any],
    strategies: dict[tuple[str, str], dict[str, str]],
    score_evs: dict[tuple[str, str, str], dict[str, str]],
) -> dict[str, object]:
    home_team = str(event["home_team"])
    away_team = str(event["away_team"])
    home_score = score_by_team(event, home_team)
    away_score = score_by_team(event, away_team)
    final_score = f"{home_score}-{away_score}"
    key = (
        compute_mpg_strategy.normalize_team(home_team),
        compute_mpg_strategy.normalize_team(away_team),
    )
    strategy = strategies.get(key)
    if strategy is None:
        raise ValueError(f"No optimal strategy found for {home_team} vs {away_team}")

    selected_outcome = outcome_for_pick(
        strategy["optimal_pick"], home_team, away_team
    )
    actual_outcome = compute_mpg_strategy.score_outcome(home_score, away_score)
    outcome_correct = selected_outcome == actual_outcome
    exact_score_correct = strategy["optimal_exact_score"] == final_score
    base_points = (
        float(strategy["optimal_pick_points"]) if outcome_correct else 0.0
    )
    actual_score_row = score_evs.get((*key, final_score))
    actual_exact_bonus_points = (
        float(actual_score_row["exact_bonus_points"])
        if actual_score_row is not None
        else 0.0
    )
    total_points = (
        base_points + actual_exact_bonus_points if exact_score_correct else base_points
    )
    return {
        "event_id": event["id"],
        "commence_time": event["commence_time"],
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "final_score": final_score,
        "optimal_pick": strategy["optimal_pick"],
        "optimal_exact_score": strategy["optimal_exact_score"],
        "outcome_correct": outcome_correct,
        "exact_score_correct": exact_score_correct,
        "base_points": base_points,
        "actual_exact_bonus_points": actual_exact_bonus_points,
        "total_points": total_points,
        "api_last_update": event.get("last_update", ""),
    }


def fetch_completed_events(sport_key: str, days_from: int) -> tuple[list[dict[str, Any]], Any]:
    result = fetch_odds.get_json(
        f"/sports/{sport_key}/scores/",
        {"daysFrom": days_from, "dateFormat": "iso"},
    )
    events = [
        event
        for event in result.data
        if event.get("completed") is True and event.get("scores") is not None
    ]
    return events, result.response


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport-key", default=DEFAULT_SPORT_KEY)
    parser.add_argument("--days-from", type=int, default=DEFAULT_DAYS_FROM)
    parser.add_argument("--completed-file", default=DEFAULT_COMPLETED_FILE)
    parser.add_argument("--strategy-file", default=DEFAULT_STRATEGY_FILE)
    parser.add_argument("--score-ev-file", default=DEFAULT_SCORE_EV_FILE)
    args = parser.parse_args()
    if args.days_from <= 0:
        raise SystemExit("--days-from must be positive")

    events, response = fetch_completed_events(args.sport_key, args.days_from)
    strategies = strategy_lookup(read_csv(args.strategy_file))
    score_evs = score_ev_lookup(read_csv(args.score_ev_file))
    existing = {
        row["event_id"]: row for row in read_csv(args.completed_file)
    }
    for event in events:
        existing[str(event["id"])] = completed_row(event, strategies, score_evs)

    merged = sorted(existing.values(), key=lambda row: str(row["commence_time"]))
    write_csv(args.completed_file, merged)

    print(f"Completed events returned by API: {len(events)}")
    print(f"Completed games in file: {len(merged)}")
    fetch_odds.print_credit_headers(response)
    print(f"Updated completed games: {args.completed_file}")


if __name__ == "__main__":
    main()
