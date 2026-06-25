#!/usr/bin/env python3
"""Compare bookmaker-injected picks under proportional and power devig."""

from __future__ import annotations

import csv
import datetime as dt
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bookmaker_injected_strategy
from odds_pipeline.processing import normalize_implied_probabilities

import analyze_bookmaker_injected_results as simulation


DEFAULT_ODDS_LOG = ROOT / "data/bookmaker_injected/bookmaker_score_odds.csv"
DEFAULT_PREDICTION_LOG = ROOT / "data/bookmaker_injected/expected_mpg_top5.csv"
DEFAULT_MPG_FILE = ROOT / "data/mpg/mpg.txt"
DEFAULT_COMPLETED_FILE = ROOT / "data/mpg/completed_games.csv"
DEFAULT_OUT_DIR = ROOT / "data/analysis/strategy_simulations/bookmaker_injected"
DEFAULT_ROLLOUTS = 200_000
DEFAULT_SEED = 20260626
METHODS = ("proportional", "power")

PICK_FIELDS = [
    "logged_at_utc",
    "submission_id",
    "match",
    "proportional_score",
    "proportional_outcome",
    "proportional_exact_score_probability",
    "proportional_expected_points",
    "power_score",
    "power_outcome",
    "power_exact_score_probability",
    "power_expected_points",
    "pick_changed",
    "expected_points_delta_power_minus_proportional",
]

RESOLVED_FIELDS = [
    "commence_time",
    "match",
    "actual_score",
    "proportional_score",
    "proportional_outcome_correct",
    "proportional_exact_score_correct",
    "proportional_realized_points",
    "power_score",
    "power_outcome_correct",
    "power_exact_score_correct",
    "power_realized_points",
    "points_delta_power_minus_proportional",
]

SUMMARY_FIELDS = [
    "method",
    "logged_submissions",
    "prediction_rows",
    "resolved_games",
    "outcome_correct",
    "exact_score_correct",
    "resolved_points",
    "expected_points",
    "simulation_rollouts",
    "sim_mean",
    "sim_p05",
    "sim_p50",
    "sim_p95",
    "realized_percentile",
]


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_csv(path: str | Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_utc(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def match_key(home_team: str, away_team: str) -> tuple[str, str]:
    return (
        bookmaker_injected_strategy.normalize_team(home_team),
        bookmaker_injected_strategy.normalize_team(away_team),
    )


def logged_submissions(
    odds_rows: list[dict[str, str]],
) -> dict[tuple[str, str, str], list[dict[str, str]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in odds_rows:
        grouped.setdefault(
            (row["submission_id"], row["match"], row["logged_at_utc"]),
            [],
        ).append(row)
    return grouped


def mpg_points_lookup(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, float]]:
    return {
        match_key(row["home_team"], row["away_team"]): {
            "home": float(row["home_odds"]),
            "draw": float(row["draw_odds"]),
            "away": float(row["away_odds"]),
        }
        for row in rows
    }


def logged_outcome_probabilities(
    prediction_rows: list[dict[str, str]],
) -> dict[tuple[str, str], dict[str, float]]:
    probabilities: dict[tuple[str, str], dict[str, float]] = {}
    for row in prediction_rows:
        key = (row["submission_id"], row["match"])
        probabilities.setdefault(key, {})
        probabilities[key][row["outcome"]] = float(row["outcome_probability"])
    return probabilities


def logged_sigmas(prediction_rows: list[dict[str, str]]) -> dict[tuple[str, str], float]:
    sigmas: dict[tuple[str, str], float] = {}
    for row in prediction_rows:
        sigmas[(row["submission_id"], row["match"])] = float(
            row.get("conditional_share_sigma", "0.01") or "0.01"
        )
    return sigmas


def outcome_shares_from_score_odds(rows: list[dict[str, str]]) -> dict[str, float]:
    implied = {
        str(index): 1.0 / float(row["odds_decimal"])
        for index, row in enumerate(rows)
    }
    probabilities = normalize_implied_probabilities(implied, "proportional")
    shares = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for index, row in enumerate(rows):
        if row["score"].strip().lower() == "other":
            continue
        outcome = bookmaker_injected_strategy.score_outcome(
            int(row["home_goals"]),
            int(row["away_goals"]),
        )
        shares[outcome] += probabilities[str(index)]
    total = sum(shares.values())
    if total <= 0:
        return {outcome: 1.0 / 3.0 for outcome in shares}
    return {outcome: probability / total for outcome, probability in shares.items()}


def complete_outcome_probabilities(
    rows: list[dict[str, str]],
    logged_probabilities: dict[str, float],
) -> dict[str, float]:
    result = dict(logged_probabilities)
    known_total = sum(result.values())
    if known_total > 1.0:
        return {outcome: result.get(outcome, 0.0) / known_total for outcome in ("home", "draw", "away")}

    missing = [outcome for outcome in ("home", "draw", "away") if outcome not in result]
    if not missing:
        return result

    fallback = outcome_shares_from_score_odds(rows)
    fallback_total = sum(fallback[outcome] for outcome in missing)
    remaining = max(0.0, 1.0 - known_total)
    if fallback_total <= 0:
        for outcome in missing:
            result[outcome] = remaining / len(missing)
    else:
        for outcome in missing:
            result[outcome] = remaining * fallback[outcome] / fallback_total
    return result


def prediction_row(
    logged_at: str,
    submission_id: str,
    match: str,
    sigma: float,
    rank: int,
    ranked: bookmaker_injected_strategy.RankedScore,
) -> dict[str, object]:
    return {
        "logged_at_utc": logged_at,
        "submission_id": submission_id,
        "match": match,
        "conditional_share_sigma": sigma,
        "rank": rank,
        "score": ranked.score,
        "outcome": ranked.outcome,
        "outcome_label": ranked.outcome_label,
        "outcome_probability": ranked.outcome_probability,
        "exact_score_probability": ranked.score_probability,
        "conditional_bettor_share": ranked.conditional_bettor_share,
        "nominal_bonus_label": ranked.bonus.nominal_label,
        "nominal_bonus_points": ranked.bonus.nominal_points,
        "expected_bonus_points": ranked.bonus.expected_points,
        "base_ev": ranked.base_ev,
        "exact_score_ev": ranked.exact_score_ev,
        "total_ev": ranked.total_ev,
        "payoff_standard_deviation": ranked.payoff_standard_deviation,
        "is_best_pick": rank == 1,
    }


def build_prediction_rows_by_method(
    odds_rows: list[dict[str, str]],
    existing_prediction_rows: list[dict[str, str]],
    points_by_game: dict[tuple[str, str], dict[str, float]],
) -> dict[str, list[dict[str, object]]]:
    logged_probabilities = logged_outcome_probabilities(existing_prediction_rows)
    sigmas = logged_sigmas(existing_prediction_rows)
    predictions_by_method = {method: [] for method in METHODS}

    for (submission_id, match, logged_at), rows in sorted(
        logged_submissions(odds_rows).items(),
        key=lambda item: (parse_utc(item[0][2]), item[0][1], item[0][0]),
    ):
        first = rows[0]
        key = match_key(first["home_team"], first["away_team"])
        if key not in points_by_game:
            continue
        probabilities = complete_outcome_probabilities(
            rows,
            logged_probabilities.get((submission_id, match), {}),
        )
        sigma = sigmas.get(
            (submission_id, match),
            bookmaker_injected_strategy.DEFAULT_CONDITIONAL_SHARE_SIGMA,
        )
        for method in METHODS:
            ranked = bookmaker_injected_strategy.rank_scores(
                rows,
                probabilities,
                points_by_game[key],
                first["home_team"],
                first["away_team"],
                sigma=sigma,
                devig_method=method,
            )
            for rank, row in enumerate(ranked[:5], start=1):
                predictions_by_method[method].append(
                    prediction_row(logged_at, submission_id, match, sigma, rank, row)
                )

    return predictions_by_method


def top_pick_rows(
    prediction_rows: list[dict[str, object]],
) -> dict[tuple[str, str, str], dict[str, object]]:
    return {
        (str(row["submission_id"]), str(row["match"]), str(row["logged_at_utc"])): row
        for row in prediction_rows
        if int(row["rank"]) == 1
    }


def build_pick_comparison_rows(
    predictions_by_method: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    proportional = top_pick_rows(predictions_by_method["proportional"])
    power = top_pick_rows(predictions_by_method["power"])
    rows: list[dict[str, object]] = []
    for key in sorted(proportional, key=lambda item: (parse_utc(item[2]), item[1], item[0])):
        if key not in power:
            continue
        prop = proportional[key]
        pwr = power[key]
        rows.append(
            {
                "logged_at_utc": key[2],
                "submission_id": key[0],
                "match": key[1],
                "proportional_score": prop["score"],
                "proportional_outcome": prop["outcome"],
                "proportional_exact_score_probability": prop["exact_score_probability"],
                "proportional_expected_points": prop["total_ev"],
                "power_score": pwr["score"],
                "power_outcome": pwr["outcome"],
                "power_exact_score_probability": pwr["exact_score_probability"],
                "power_expected_points": pwr["total_ev"],
                "pick_changed": (
                    prop["score"] != pwr["score"]
                    or prop["outcome"] != pwr["outcome"]
                ),
                "expected_points_delta_power_minus_proportional": (
                    float(pwr["total_ev"]) - float(prop["total_ev"])
                ),
            }
        )
    return rows


def scored_by_match(
    picks: list[simulation.ScoredPick],
) -> dict[tuple[str, str], simulation.ScoredPick]:
    return {(pick.commence_time, pick.match): pick for pick in picks}


def build_resolved_rows(
    scored_by_method: dict[str, list[simulation.ScoredPick]],
) -> list[dict[str, object]]:
    proportional = scored_by_match(scored_by_method["proportional"])
    power = scored_by_match(scored_by_method["power"])
    rows: list[dict[str, object]] = []
    for key in sorted(proportional):
        if key not in power:
            continue
        prop = proportional[key]
        pwr = power[key]
        rows.append(
            {
                "commence_time": key[0],
                "match": key[1],
                "actual_score": prop.actual_score,
                "proportional_score": prop.selected_score,
                "proportional_outcome_correct": prop.outcome_correct,
                "proportional_exact_score_correct": prop.exact_score_correct,
                "proportional_realized_points": prop.realized_points,
                "power_score": pwr.selected_score,
                "power_outcome_correct": pwr.outcome_correct,
                "power_exact_score_correct": pwr.exact_score_correct,
                "power_realized_points": pwr.realized_points,
                "points_delta_power_minus_proportional": (
                    pwr.realized_points - prop.realized_points
                ),
            }
        )
    return rows


def simulation_summary(
    method: str,
    prediction_rows: list[dict[str, object]],
    picks: list[simulation.ScoredPick],
    rollouts: int,
    seed: int,
) -> dict[str, object]:
    totals = simulation.simulate_totals(picks, rollouts, seed)
    realized = sum(pick.realized_points for pick in picks)
    return {
        "method": method,
        "logged_submissions": len(prediction_rows) // 5,
        "prediction_rows": len(prediction_rows),
        "resolved_games": len(picks),
        "outcome_correct": sum(pick.outcome_correct for pick in picks),
        "exact_score_correct": sum(pick.exact_score_correct for pick in picks),
        "resolved_points": realized,
        "expected_points": sum(pick.expected_points for pick in picks),
        "simulation_rollouts": rollouts,
        "sim_mean": float(totals.mean()),
        "sim_p05": float(np.quantile(totals, 0.05)),
        "sim_p50": float(np.quantile(totals, 0.50)),
        "sim_p95": float(np.quantile(totals, 0.95)),
        "realized_percentile": float((totals <= realized).mean()),
    }


def stringify_rows(rows: list[dict[str, object]]) -> list[dict[str, str]]:
    return [
        {key: str(value) for key, value in row.items()}
        for row in rows
    ]


def main() -> None:
    odds_rows = read_csv(DEFAULT_ODDS_LOG)
    existing_prediction_rows = read_csv(DEFAULT_PREDICTION_LOG)
    mpg_rows = read_csv(DEFAULT_MPG_FILE)
    completed_rows = read_csv(DEFAULT_COMPLETED_FILE)
    points_by_game = mpg_points_lookup(mpg_rows)

    predictions_by_method = build_prediction_rows_by_method(
        odds_rows,
        existing_prediction_rows,
        points_by_game,
    )
    scored_by_method = {
        method: simulation.score_completed_picks(
            stringify_rows(predictions),
            completed_rows,
            mpg_rows,
            require_pre_kickoff=True,
        )
        for method, predictions in predictions_by_method.items()
    }

    pick_rows = build_pick_comparison_rows(predictions_by_method)
    resolved_rows = build_resolved_rows(scored_by_method)
    summary_rows = [
        simulation_summary(
            method,
            predictions_by_method[method],
            scored_by_method[method],
            DEFAULT_ROLLOUTS,
            DEFAULT_SEED + index,
        )
        for index, method in enumerate(METHODS)
    ]

    DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    for method, predictions in predictions_by_method.items():
        write_csv(
            DEFAULT_OUT_DIR / f"devig_method_{method}_reconstructed_predictions.csv",
            predictions,
            bookmaker_injected_strategy.PREDICTION_LOG_FIELDS,
        )
    write_csv(DEFAULT_OUT_DIR / "devig_method_pick_comparison.csv", pick_rows, PICK_FIELDS)
    write_csv(DEFAULT_OUT_DIR / "devig_method_resolved_points.csv", resolved_rows, RESOLVED_FIELDS)
    write_csv(
        DEFAULT_OUT_DIR / "devig_method_simulation_summary.csv",
        summary_rows,
        SUMMARY_FIELDS,
    )

    changed = sum(row["pick_changed"] is True for row in pick_rows)
    print(f"Compared submissions: {len(pick_rows)}")
    print(f"Changed top picks: {changed}")
    for row in summary_rows:
        print(
            f"{row['method']}: resolved_games={row['resolved_games']}, "
            f"resolved_points={float(row['resolved_points']):.1f}, "
            f"expected_points={float(row['expected_points']):.1f}, "
            f"sim_mean={float(row['sim_mean']):.1f}, "
            f"realized_percentile={float(row['realized_percentile']):.3f}"
        )
    if len(summary_rows) == 2:
        delta = float(summary_rows[1]["resolved_points"]) - float(summary_rows[0]["resolved_points"])
        print(f"Power minus proportional resolved points: {delta:.1f}")
    print(f"Saved outputs under: {DEFAULT_OUT_DIR}")


if __name__ == "__main__":
    main()
