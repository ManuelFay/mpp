#!/usr/bin/env python3
"""
Process the latest World Cup odds snapshot into per-game outcome probabilities
and exact-score probability distributions.

Input:
  data/odds_snapshots/latest.csv

Output:
  data/processed/latest_game_probabilities.csv
  data/processed/latest_exact_score_probabilities.csv
  data/processed/latest_exact_score_probabilities_calibrated.csv
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

from odds_pipeline import filters


DEFAULT_IN = "data/odds_snapshots/latest.csv"
DEFAULT_OUT = "data/processed/latest_game_probabilities.csv"
DEFAULT_EXACT_SCORE_OUT = "data/processed/latest_exact_score_probabilities.csv"
DEFAULT_CALIBRATED_EXACT_SCORE_OUT = "data/processed/latest_exact_score_probabilities_calibrated.csv"
DEFAULT_CALIBRATION_MULTIPLIERS_OUT = "data/processed/latest_score_shape_calibration_multipliers.csv"
DEFAULT_HISTORICAL_ODDS = "data/historical/odds_2022.csv"
DEFAULT_MARKET = "h2h"
MODEL_MAX_GOALS = 14
SCORE_GRID_MAX = 4
CALIBRATION_STRENGTH = 0.35
CALIBRATION_MIN_MULTIPLIER = 0.70
CALIBRATION_MAX_MULTIPLIER = 1.35

OUT_FIELDS = [
    "event_id",
    "commence_time",
    "home_team",
    "away_team",
    "market",
    "bookmaker_count",
    "home_probability",
    "draw_probability",
    "away_probability",
    "home_avg_odds",
    "draw_avg_odds",
    "away_avg_odds",
    "favorite",
    "favorite_probability",
    "favorite_gap_to_second",
]

SCORE_FIELDS = [
    "event_id",
    "commence_time",
    "home_team",
    "away_team",
    "h2h_bookmaker_count",
    "total_line_count",
    "spread_line_count",
    "home_lambda",
    "away_lambda",
    "model_home_win_probability",
    "model_draw_probability",
    "model_away_win_probability",
    "grid_home_win_probability",
    "grid_draw_probability",
    "grid_away_win_probability",
    "other_home_win_probability",
    "other_draw_probability",
    "other_away_win_probability",
    "model_loss",
]

for home_goals in range(SCORE_GRID_MAX + 1):
    for away_goals in range(SCORE_GRID_MAX + 1):
        SCORE_FIELDS.append(f"score_{home_goals}_{away_goals}_probability")
SCORE_FIELDS.append("other_probability")

CALIBRATED_SCORE_FIELDS = SCORE_FIELDS + [
    "calibration_strength",
    "calibration_min_multiplier",
    "calibration_max_multiplier",
]

CALIBRATION_MULTIPLIER_FIELDS = [
    "score_bucket",
    "actual_2022_group_frequency",
    "expected_2022_h2h_poisson_probability",
    "raw_actual_to_expected_ratio",
    "calibration_multiplier",
]


def read_rows(path: str | Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def grouped_events(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    events: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        events[row["event_id"]].append(row)
    return events


def normalized_pair_probability(first_price: float, second_price: float) -> tuple[float, float]:
    first_implied = 1 / first_price
    second_implied = 1 / second_price
    total = first_implied + second_implied
    return first_implied / total, second_implied / total


def normalized_h2h_by_event(event_rows: list[dict[str, str]], market: str) -> tuple[dict[str, float], dict[str, float], int]:
    first = event_rows[0]
    home_team = first["home_team"]
    away_team = first["away_team"]

    bookmaker_outcomes: dict[str, dict[str, float]] = defaultdict(dict)
    for row in event_rows:
        if row["market"] != market or not row["price"]:
            continue
        bookmaker_outcomes[row["bookmaker_key"]][row["outcome"]] = float(row["price"])

    normalized_probabilities: dict[str, list[float]] = defaultdict(list)
    odds: dict[str, list[float]] = defaultdict(list)

    for outcomes in bookmaker_outcomes.values():
        required_outcomes = {home_team, "Draw", away_team}
        if set(outcomes) != required_outcomes:
            continue
        if not filters.valid_h2h_outcomes(outcomes):
            continue

        implied = {outcome: 1 / price for outcome, price in outcomes.items()}
        implied_total = sum(implied.values())
        for outcome, implied_probability in implied.items():
            normalized_probabilities[outcome].append(implied_probability / implied_total)
            odds[outcome].append(outcomes[outcome])

    bookmaker_count = len(normalized_probabilities[home_team])
    if bookmaker_count == 0:
        return {}, {}, 0

    probabilities = {
        home_team: mean(normalized_probabilities[home_team]),
        "Draw": mean(normalized_probabilities["Draw"]),
        away_team: mean(normalized_probabilities[away_team]),
    }
    average_odds = {
        home_team: mean(odds[home_team]),
        "Draw": mean(odds["Draw"]),
        away_team: mean(odds[away_team]),
    }
    return probabilities, average_odds, bookmaker_count


def process_rows(rows: list[dict[str, str]], market: str) -> list[dict[str, str | float | int]]:
    events = grouped_events(rows)

    output_rows: list[dict[str, str | float | int]] = []

    for event_id, event_rows in sorted(events.items(), key=lambda item: item[1][0]["commence_time"]):
        first = event_rows[0]
        home_team = first["home_team"]
        away_team = first["away_team"]

        probabilities, average_odds, bookmaker_count = normalized_h2h_by_event(event_rows, market)
        if bookmaker_count == 0:
            continue

        ranked_outcomes = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
        favorite, favorite_probability = ranked_outcomes[0]
        favorite_gap = favorite_probability - ranked_outcomes[1][1]

        output_rows.append(
            {
                "event_id": event_id,
                "commence_time": first["commence_time"],
                "home_team": home_team,
                "away_team": away_team,
                "market": market,
                "bookmaker_count": bookmaker_count,
                "home_probability": probabilities[home_team],
                "draw_probability": probabilities["Draw"],
                "away_probability": probabilities[away_team],
                "home_avg_odds": average_odds[home_team],
                "draw_avg_odds": average_odds["Draw"],
                "away_avg_odds": average_odds[away_team],
                "favorite": favorite,
                "favorite_probability": favorite_probability,
                "favorite_gap_to_second": favorite_gap,
            }
        )

    return output_rows


def poisson_pmf(rate: float, max_goals: int) -> list[float]:
    probabilities = [math.exp(-rate)]
    for goals in range(1, max_goals + 1):
        probabilities.append(probabilities[-1] * rate / goals)
    return probabilities


def score_matrix(home_lambda: float, away_lambda: float, max_goals: int) -> list[list[float]]:
    home_probs = poisson_pmf(home_lambda, max_goals)
    away_probs = poisson_pmf(away_lambda, max_goals)
    return [[home_prob * away_prob for away_prob in away_probs] for home_prob in home_probs]


def matrix_mass(matrix: list[list[float]]) -> float:
    return sum(sum(row) for row in matrix)


def h2h_model_probabilities(matrix: list[list[float]]) -> dict[str, float]:
    home = draw = away = 0.0
    for home_goals, row in enumerate(matrix):
        for away_goals, probability in enumerate(row):
            if home_goals > away_goals:
                home += probability
            elif home_goals == away_goals:
                draw += probability
            else:
                away += probability

    total = home + draw + away
    return {"home": home / total, "draw": draw / total, "away": away / total}


def total_over_probability(matrix: list[list[float]], point: float) -> float:
    over = under = 0.0
    for home_goals, row in enumerate(matrix):
        for away_goals, probability in enumerate(row):
            total_goals = home_goals + away_goals
            if total_goals > point:
                over += probability
            elif total_goals < point:
                under += probability

    denominator = over + under
    return over / denominator if denominator else 0.5


def home_spread_probability(matrix: list[list[float]], home_point: float) -> float:
    cover = fail = 0.0
    for home_goals, row in enumerate(matrix):
        for away_goals, probability in enumerate(row):
            adjusted_margin = home_goals + home_point - away_goals
            if adjusted_margin > 0:
                cover += probability
            elif adjusted_margin < 0:
                fail += probability

    denominator = cover + fail
    return cover / denominator if denominator else 0.5


def collect_total_targets(event_rows: list[dict[str, str]]) -> list[tuple[float, float, int]]:
    grouped: dict[tuple[str, float], dict[str, float]] = defaultdict(dict)
    for row in event_rows:
        if row["market"] != "totals" or not row["price"] or not row["point"]:
            continue
        grouped[(row["bookmaker_key"], float(row["point"]))][row["outcome"]] = float(row["price"])

    by_point: dict[float, list[float]] = defaultdict(list)
    for (_, point), outcomes in grouped.items():
        if {"Over", "Under"} <= set(outcomes):
            over_probability, _ = normalized_pair_probability(outcomes["Over"], outcomes["Under"])
            by_point[point].append(over_probability)

    return [(point, mean(probabilities), len(probabilities)) for point, probabilities in sorted(by_point.items())]


def collect_spread_targets(event_rows: list[dict[str, str]]) -> list[tuple[float, float, int]]:
    first = event_rows[0]
    home_team = first["home_team"]
    away_team = first["away_team"]

    grouped: dict[tuple[str, float], dict[str, tuple[float, float]]] = defaultdict(dict)
    for row in event_rows:
        if row["market"] != "spreads" or not row["price"] or not row["point"]:
            continue
        point = float(row["point"])
        grouped[(row["bookmaker_key"], abs(point))][row["outcome"]] = (float(row["price"]), point)

    by_home_point: dict[float, list[float]] = defaultdict(list)
    for outcomes in grouped.values():
        if home_team not in outcomes or away_team not in outcomes:
            continue
        home_price, home_point = outcomes[home_team]
        away_price, away_point = outcomes[away_team]
        if round(home_point + away_point, 6) != 0:
            continue
        home_probability, _ = normalized_pair_probability(home_price, away_price)
        by_home_point[home_point].append(home_probability)

    return [(point, mean(probabilities), len(probabilities)) for point, probabilities in sorted(by_home_point.items())]


def clamp_probability(probability: float) -> float:
    return min(max(probability, 1e-6), 1 - 1e-6)


def model_loss(
    home_lambda: float,
    away_lambda: float,
    h2h_probabilities: dict[str, float],
    h2h_bookmaker_count: int,
    total_targets: list[tuple[float, float, int]],
    spread_targets: list[tuple[float, float, int]],
) -> float:
    matrix = score_matrix(home_lambda, away_lambda, MODEL_MAX_GOALS)
    h2h_model = h2h_model_probabilities(matrix)
    loss = 0.0

    h2h_weight = 2.0 * math.sqrt(h2h_bookmaker_count)
    for key, target in [
        ("home", h2h_probabilities["home"]),
        ("draw", h2h_probabilities["draw"]),
        ("away", h2h_probabilities["away"]),
    ]:
        loss += h2h_weight * (clamp_probability(h2h_model[key]) - clamp_probability(target)) ** 2

    for point, target, count in total_targets:
        predicted = total_over_probability(matrix, point)
        loss += math.sqrt(count) * (clamp_probability(predicted) - clamp_probability(target)) ** 2

    for home_point, target, count in spread_targets:
        predicted = home_spread_probability(matrix, home_point)
        loss += math.sqrt(count) * (clamp_probability(predicted) - clamp_probability(target)) ** 2

    return loss


def initial_lambdas(h2h_probabilities: dict[str, float], total_targets: list[tuple[float, float, int]]) -> tuple[float, float]:
    total_goals = 2.6
    if total_targets:
        main_point, over_probability, _ = max(total_targets, key=lambda item: item[2])
        total_goals += (main_point - 2.5) * 0.35 + (over_probability - 0.5) * 1.2
        total_goals = min(max(total_goals, 1.2), 5.2)

    margin_signal = (h2h_probabilities["home"] - h2h_probabilities["away"]) * 2.2
    margin_signal = min(max(margin_signal, -2.2), 2.2)
    home_lambda = min(max((total_goals + margin_signal) / 2, 0.1), 5.8)
    away_lambda = min(max((total_goals - margin_signal) / 2, 0.1), 5.8)
    return home_lambda, away_lambda


def fit_lambdas(
    h2h_probabilities: dict[str, float],
    h2h_bookmaker_count: int,
    total_targets: list[tuple[float, float, int]],
    spread_targets: list[tuple[float, float, int]],
) -> tuple[float, float, float]:
    home_lambda, away_lambda = initial_lambdas(h2h_probabilities, total_targets)
    best_loss = model_loss(
        home_lambda,
        away_lambda,
        h2h_probabilities,
        h2h_bookmaker_count,
        total_targets,
        spread_targets,
    )

    step = 0.5
    while step >= 0.01:
        improved = True
        while improved:
            improved = False
            candidates = [
                (home_lambda + home_delta * step, away_lambda + away_delta * step)
                for home_delta in [-1, 0, 1]
                for away_delta in [-1, 0, 1]
                if home_delta or away_delta
            ]
            for candidate_home, candidate_away in candidates:
                if not (0.05 <= candidate_home <= 6.0 and 0.05 <= candidate_away <= 6.0):
                    continue
                candidate_loss = model_loss(
                    candidate_home,
                    candidate_away,
                    h2h_probabilities,
                    h2h_bookmaker_count,
                    total_targets,
                    spread_targets,
                )
                if candidate_loss < best_loss:
                    home_lambda = candidate_home
                    away_lambda = candidate_away
                    best_loss = candidate_loss
                    improved = True
        step /= 2

    return home_lambda, away_lambda, best_loss


def score_bucket(home_goals: int, away_goals: int) -> str:
    if 0 <= home_goals <= SCORE_GRID_MAX and 0 <= away_goals <= SCORE_GRID_MAX:
        return f"{home_goals}-{away_goals}"
    return "other"


def score_buckets() -> list[str]:
    return [f"{home_goals}-{away_goals}" for home_goals in range(SCORE_GRID_MAX + 1) for away_goals in range(SCORE_GRID_MAX + 1)] + ["other"]


def score_distribution_from_lambdas(home_lambda: float, away_lambda: float) -> dict[str, float]:
    home_probs = poisson_pmf(home_lambda, SCORE_GRID_MAX)
    away_probs = poisson_pmf(away_lambda, SCORE_GRID_MAX)
    distribution = {bucket: 0.0 for bucket in score_buckets()}

    for home_goals in range(SCORE_GRID_MAX + 1):
        for away_goals in range(SCORE_GRID_MAX + 1):
            distribution[f"{home_goals}-{away_goals}"] = home_probs[home_goals] * away_probs[away_goals]

    distribution["other"] = max(0.0, 1 - sum(distribution.values()))
    return distribution


def build_score_row(
    base_fields: dict[str, str | float | int],
    score_probabilities: dict[str, float],
    other_home_win: float,
    other_draw: float,
    other_away_win: float,
) -> dict[str, str | float | int]:
    grid_home_win = 0.0
    grid_draw = 0.0
    grid_away_win = 0.0

    for column, probability in score_probabilities.items():
        home_goals, away_goals = tuple(map(int, column.split("_")[1:3]))
        if home_goals > away_goals:
            grid_home_win += probability
        elif home_goals == away_goals:
            grid_draw += probability
        else:
            grid_away_win += probability

    other_probability = other_home_win + other_draw + other_away_win
    return {
        **base_fields,
        "model_home_win_probability": grid_home_win + other_home_win,
        "model_draw_probability": grid_draw + other_draw,
        "model_away_win_probability": grid_away_win + other_away_win,
        "grid_home_win_probability": grid_home_win,
        "grid_draw_probability": grid_draw,
        "grid_away_win_probability": grid_away_win,
        "other_home_win_probability": other_home_win,
        "other_draw_probability": other_draw,
        "other_away_win_probability": other_away_win,
        **score_probabilities,
        "other_probability": other_probability,
    }


def process_exact_scores(rows: list[dict[str, str]], market: str) -> list[dict[str, str | float | int]]:
    events = grouped_events(rows)
    output_rows: list[dict[str, str | float | int]] = []

    for event_id, event_rows in sorted(events.items(), key=lambda item: item[1][0]["commence_time"]):
        first = event_rows[0]
        home_team = first["home_team"]
        away_team = first["away_team"]

        probabilities, _, bookmaker_count = normalized_h2h_by_event(event_rows, market)
        if bookmaker_count == 0:
            continue

        h2h_probabilities = {
            "home": probabilities[home_team],
            "draw": probabilities["Draw"],
            "away": probabilities[away_team],
        }
        total_targets = collect_total_targets(event_rows)
        spread_targets = collect_spread_targets(event_rows)
        home_lambda, away_lambda, loss = fit_lambdas(
            h2h_probabilities,
            bookmaker_count,
            total_targets,
            spread_targets,
        )

        home_probs = poisson_pmf(home_lambda, SCORE_GRID_MAX)
        away_probs = poisson_pmf(away_lambda, SCORE_GRID_MAX)
        full_matrix = score_matrix(home_lambda, away_lambda, MODEL_MAX_GOALS)
        model_h2h = h2h_model_probabilities(full_matrix)
        score_probabilities = {
            f"score_{home_goals}_{away_goals}_probability": home_probs[home_goals] * away_probs[away_goals]
            for home_goals in range(SCORE_GRID_MAX + 1)
            for away_goals in range(SCORE_GRID_MAX + 1)
        }
        grid_home_win = sum(
            probability
            for column, probability in score_probabilities.items()
            for home_goals, away_goals in [tuple(map(int, column.split("_")[1:3]))]
            if home_goals > away_goals
        )
        grid_draw = sum(
            probability
            for column, probability in score_probabilities.items()
            for home_goals, away_goals in [tuple(map(int, column.split("_")[1:3]))]
            if home_goals == away_goals
        )
        grid_away_win = sum(
            probability
            for column, probability in score_probabilities.items()
            for home_goals, away_goals in [tuple(map(int, column.split("_")[1:3]))]
            if home_goals < away_goals
        )
        other_home_win = max(0.0, model_h2h["home"] - grid_home_win)
        other_draw = max(0.0, model_h2h["draw"] - grid_draw)
        other_away_win = max(0.0, model_h2h["away"] - grid_away_win)

        base_fields: dict[str, str | float | int] = {
            "event_id": event_id,
            "commence_time": first["commence_time"],
            "home_team": home_team,
            "away_team": away_team,
            "h2h_bookmaker_count": bookmaker_count,
            "total_line_count": len(total_targets),
            "spread_line_count": len(spread_targets),
            "home_lambda": home_lambda,
            "away_lambda": away_lambda,
            "model_loss": loss,
        }
        output_rows.append(build_score_row(base_fields, score_probabilities, other_home_win, other_draw, other_away_win))

    return output_rows


def learn_score_shape_calibration(
    historical_odds_file: str | Path,
) -> tuple[dict[str, float], list[dict[str, str | float]]]:
    rows = read_rows(historical_odds_file)
    group_rows = [row for row in rows if row["stage"].startswith("Group ")]
    buckets = score_buckets()
    actual = {bucket: 0.0 for bucket in buckets}
    expected = {bucket: 0.0 for bucket in buckets}

    for row in group_rows:
        actual[score_bucket(int(row["home_score"]), int(row["away_score"]))] += 1 / len(group_rows)
        h2h_probabilities = {
            "home": float(row["home_vig_free_probability"]),
            "draw": float(row["draw_vig_free_probability"]),
            "away": float(row["away_vig_free_probability"]),
        }
        home_lambda, away_lambda, _ = fit_lambdas(h2h_probabilities, 1, [], [])
        for bucket, probability in score_distribution_from_lambdas(home_lambda, away_lambda).items():
            expected[bucket] += probability / len(group_rows)

    multipliers: dict[str, float] = {}
    multiplier_rows: list[dict[str, str | float]] = []
    for bucket in buckets:
        raw_ratio = actual[bucket] / expected[bucket] if expected[bucket] > 0 else 1.0
        multiplier = 1 + CALIBRATION_STRENGTH * (raw_ratio - 1)
        multiplier = min(max(multiplier, CALIBRATION_MIN_MULTIPLIER), CALIBRATION_MAX_MULTIPLIER)
        multipliers[bucket] = multiplier
        multiplier_rows.append(
            {
                "score_bucket": bucket,
                "actual_2022_group_frequency": actual[bucket],
                "expected_2022_h2h_poisson_probability": expected[bucket],
                "raw_actual_to_expected_ratio": raw_ratio,
                "calibration_multiplier": multiplier,
            }
        )

    return multipliers, multiplier_rows


def calibrate_exact_score_rows(
    rows: list[dict[str, str | float | int]],
    multipliers: dict[str, float],
) -> list[dict[str, str | float | int]]:
    calibrated_rows: list[dict[str, str | float | int]] = []

    for row in rows:
        weighted_scores: dict[str, float] = {}
        total_mass = 0.0
        for home_goals in range(SCORE_GRID_MAX + 1):
            for away_goals in range(SCORE_GRID_MAX + 1):
                bucket = f"{home_goals}-{away_goals}"
                column = f"score_{home_goals}_{away_goals}_probability"
                weighted_probability = float(row[column]) * multipliers[bucket]
                weighted_scores[column] = weighted_probability
                total_mass += weighted_probability

        other_multiplier = multipliers["other"]
        weighted_other_home = float(row["other_home_win_probability"]) * other_multiplier
        weighted_other_draw = float(row["other_draw_probability"]) * other_multiplier
        weighted_other_away = float(row["other_away_win_probability"]) * other_multiplier
        total_mass += weighted_other_home + weighted_other_draw + weighted_other_away

        normalized_scores = {column: probability / total_mass for column, probability in weighted_scores.items()}
        base_fields = {
            field: row[field]
            for field in [
                "event_id",
                "commence_time",
                "home_team",
                "away_team",
                "h2h_bookmaker_count",
                "total_line_count",
                "spread_line_count",
                "home_lambda",
                "away_lambda",
                "model_loss",
            ]
        }
        calibrated_row = build_score_row(
            base_fields,
            normalized_scores,
            weighted_other_home / total_mass,
            weighted_other_draw / total_mass,
            weighted_other_away / total_mass,
        )
        calibrated_row["calibration_strength"] = CALIBRATION_STRENGTH
        calibrated_row["calibration_min_multiplier"] = CALIBRATION_MIN_MULTIPLIER
        calibrated_row["calibration_max_multiplier"] = CALIBRATION_MAX_MULTIPLIER
        calibrated_rows.append(calibrated_row)

    return calibrated_rows


def write_rows(rows: list[dict[str, str | float | int]], path: str | Path, fieldnames: list[str]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def process_snapshot(
    in_file: str | Path = DEFAULT_IN,
    out: str | Path = DEFAULT_OUT,
    exact_score_out: str | Path = DEFAULT_EXACT_SCORE_OUT,
    calibrated_exact_score_out: str | Path = DEFAULT_CALIBRATED_EXACT_SCORE_OUT,
    calibration_multipliers_out: str | Path = DEFAULT_CALIBRATION_MULTIPLIERS_OUT,
    historical_odds_file: str | Path = DEFAULT_HISTORICAL_ODDS,
    market: str = DEFAULT_MARKET,
) -> dict[str, int | str]:
    raw_rows = read_rows(in_file)
    rows = filters.filter_snapshot_rows(raw_rows)
    output_rows = process_rows(rows, market)
    exact_score_rows = process_exact_scores(rows, market)
    multipliers, multiplier_rows = learn_score_shape_calibration(historical_odds_file)
    calibrated_exact_score_rows = calibrate_exact_score_rows(exact_score_rows, multipliers)
    write_rows(output_rows, out, OUT_FIELDS)
    write_rows(exact_score_rows, exact_score_out, SCORE_FIELDS)
    write_rows(calibrated_exact_score_rows, calibrated_exact_score_out, CALIBRATED_SCORE_FIELDS)
    write_rows(multiplier_rows, calibration_multipliers_out, CALIBRATION_MULTIPLIER_FIELDS)

    return {
        "raw_rows": len(raw_rows),
        "filtered_rows": len(rows),
        "games": len(output_rows),
        "out": str(out),
        "exact_score_out": str(exact_score_out),
        "calibrated_exact_score_out": str(calibrated_exact_score_out),
        "calibration_multipliers_out": str(calibration_multipliers_out),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in-file", default=DEFAULT_IN)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--exact-score-out", default=DEFAULT_EXACT_SCORE_OUT)
    parser.add_argument("--calibrated-exact-score-out", default=DEFAULT_CALIBRATED_EXACT_SCORE_OUT)
    parser.add_argument("--calibration-multipliers-out", default=DEFAULT_CALIBRATION_MULTIPLIERS_OUT)
    parser.add_argument("--historical-odds-file", default=DEFAULT_HISTORICAL_ODDS)
    parser.add_argument("--market", default=DEFAULT_MARKET)
    args = parser.parse_args()

    summary = process_snapshot(
        in_file=args.in_file,
        out=args.out,
        exact_score_out=args.exact_score_out,
        calibrated_exact_score_out=args.calibrated_exact_score_out,
        calibration_multipliers_out=args.calibration_multipliers_out,
        historical_odds_file=args.historical_odds_file,
        market=args.market,
    )

    print(f"Input rows read: {summary['raw_rows']}")
    print(f"Rows retained after odds filters: {summary['filtered_rows']}")
    print(f"Games processed: {summary['games']}")
    print(f"Saved probabilities: {summary['out']}")
    print(f"Saved exact score probabilities: {summary['exact_score_out']}")
    print(f"Saved calibrated exact score probabilities: {summary['calibrated_exact_score_out']}")
    print(f"Saved score shape calibration multipliers: {summary['calibration_multipliers_out']}")


if __name__ == "__main__":
    main()
