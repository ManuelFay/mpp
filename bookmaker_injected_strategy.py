#!/usr/bin/env python3
"""Rank bookmaker-injected MPG exact scores with bettor-share uncertainty."""

from __future__ import annotations

import argparse
import csv
import datetime
import math
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from odds_pipeline import elimination
from odds_pipeline.processing import DEFAULT_DEVIG_METHOD, normalize_implied_probabilities


DEFAULT_MPG_FILE = "data/mpg/mpg.txt"
DEFAULT_PROBABILITY_FILE = "data/processed/latest_game_probabilities.csv"
DEFAULT_CONDITIONAL_SHARE_SIGMA = 0.01
DEFAULT_ODDS_LOG = "data/bookmaker_injected/bookmaker_score_odds.csv"
DEFAULT_PREDICTION_LOG = "data/bookmaker_injected/expected_mpg_top5.csv"

ODDS_LOG_FIELDS = [
    "logged_at_utc",
    "submission_id",
    "match",
    "home_team",
    "away_team",
    "home_goals",
    "away_goals",
    "score",
    "odds_decimal",
    "bet_percentage",
]

PREDICTION_LOG_FIELDS = [
    "logged_at_utc",
    "submission_id",
    "match",
    "conditional_share_sigma",
    "bettor_share_transfer",
    "rank",
    "score",
    "outcome",
    "outcome_label",
    "outcome_probability",
    "exact_score_probability",
    "conditional_bettor_share",
    "nominal_bonus_label",
    "nominal_bonus_points",
    "expected_bonus_points",
    "base_ev",
    "exact_score_ev",
    "total_ev",
    "payoff_standard_deviation",
    "is_best_pick",
]

TEAM_ALIASES = {
    "Bosnia": "Bosnia & Herzegovina",
    "Bosnia-Herzegovina": "Bosnia & Herzegovina",
    "Cabo Verde": "Cape Verde",
    "Cote d'Ivoire": "Ivory Coast",
    "Korea": "South Korea",
    "Czechia": "Czech Republic",
    "Curacao": "Curaçao",
    "RD Congo": "DR Congo",
    "United States": "USA",
}


@dataclass(frozen=True)
class BonusDistribution:
    nominal_label: str
    nominal_points: float
    expected_points: float
    variance: float


@dataclass(frozen=True)
class RankedScore:
    score: str
    outcome: str
    outcome_label: str
    outcome_probability: float
    score_probability: float
    conditional_bettor_share: float
    bonus: BonusDistribution
    base_ev: float
    exact_score_ev: float
    total_ev: float
    payoff_standard_deviation: float


def normalize_team(team: str) -> str:
    stripped = team.strip()
    return TEAM_ALIASES.get(stripped, stripped)


def normal_cdf(value: float, mean: float, sigma: float) -> float:
    return 0.5 * (1.0 + math.erf((value - mean) / (sigma * math.sqrt(2.0))))


def nominal_bonus(conditional_share: float) -> tuple[str, float]:
    if conditional_share > 0.30:
        return "Exact", 20.0
    if conditional_share >= 0.20:
        return "Rare", 30.0
    if conditional_share >= 0.05:
        return "Tres rare", 50.0
    if conditional_share >= 0.005:
        return "Mega rare", 70.0
    return "Ultra rare", 100.0


def bonus_distribution(
    conditional_share: float,
    sigma: float = DEFAULT_CONDITIONAL_SHARE_SIGMA,
) -> BonusDistribution:
    """Return bonus moments after Gaussian uncertainty around bettor share.

    Values below zero and above one are effectively clamped because the outer
    bonus tiers extend to negative and positive infinity.
    """
    label, points = nominal_bonus(conditional_share)
    if sigma <= 0:
        return BonusDistribution(label, points, points, 0.0)

    thresholds = (0.005, 0.05, 0.20, 0.30)
    cdfs = [normal_cdf(value, conditional_share, sigma) for value in thresholds]
    tier_probabilities = (
        cdfs[0],
        cdfs[1] - cdfs[0],
        cdfs[2] - cdfs[1],
        cdfs[3] - cdfs[2],
        1.0 - cdfs[3],
    )
    tier_points = (100.0, 70.0, 50.0, 30.0, 20.0)
    expected = sum(probability * bonus for probability, bonus in zip(tier_probabilities, tier_points))
    second_moment = sum(
        probability * bonus * bonus
        for probability, bonus in zip(tier_probabilities, tier_points)
    )
    return BonusDistribution(label, points, expected, second_moment - expected * expected)


def score_outcome(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if home_goals < away_goals:
        return "away"
    return "draw"


def rank_scores(
    rows: Iterable[dict[str, str]],
    outcome_probabilities: dict[str, float],
    outcome_points: dict[str, float],
    home_team: str,
    away_team: str,
    sigma: float = DEFAULT_CONDITIONAL_SHARE_SIGMA,
    devig_method: str = DEFAULT_DEVIG_METHOD,
    game_stage: str = "",
    transfer_bettor_shares: bool = False,
) -> list[RankedScore]:
    parsed = list(rows)
    score_probabilities = normalize_implied_probabilities(
        {
            str(index): 1.0 / float(row["odds_decimal"])
            for index, row in enumerate(parsed)
        },
        devig_method,
    )
    transition: dict[str, float] | None = None
    if elimination.is_elimination_stage(game_stage):
        outcome_probabilities, transition = elimination.corrected_outcome_probabilities(
            outcome_probabilities["home"],
            outcome_probabilities["draw"],
            outcome_probabilities["away"],
        )
        score_probabilities = adjust_bookmaker_exact_score_probabilities(
            parsed,
            score_probabilities,
            transition,
        )
    bettor_percentages = {
        str(index): float(row["bet_percentage"])
        for index, row in enumerate(parsed)
    }
    if transfer_bettor_shares and transition is not None:
        bettor_percentages = adjust_bookmaker_bettor_percentages(
            parsed,
            bettor_percentages,
            transition,
        )
    bettor_totals = {"home": 0.0, "draw": 0.0, "away": 0.0}

    for index, row in enumerate(parsed):
        if row["score"].strip().lower() == "other":
            continue
        outcome = score_outcome(int(row["home_goals"]), int(row["away_goals"]))
        bettor_totals[outcome] += bettor_percentages[str(index)]

    ranked: list[RankedScore] = []
    for index, row in enumerate(parsed):
        score = row["score"].strip()
        if score.lower() == "other":
            continue

        outcome = score_outcome(int(row["home_goals"]), int(row["away_goals"]))
        score_probability = score_probabilities[str(index)]
        conditional_share = (
            bettor_percentages[str(index)] / bettor_totals[outcome]
            if bettor_totals[outcome] > 0
            else 0.0
        )
        bonus = bonus_distribution(conditional_share, sigma)
        base_points = outcome_points[outcome]
        outcome_probability = outcome_probabilities[outcome]
        base_ev = outcome_probability * base_points
        exact_score_ev = score_probability * bonus.expected_points
        total_ev = base_ev + exact_score_ev

        bonus_second_moment = bonus.variance + bonus.expected_points**2
        payoff_second_moment = (
            (outcome_probability - score_probability) * base_points**2
            + score_probability
            * (base_points**2 + 2.0 * base_points * bonus.expected_points + bonus_second_moment)
        )
        payoff_variance = max(0.0, payoff_second_moment - total_ev**2)
        outcome_label = home_team if outcome == "home" else away_team if outcome == "away" else "Draw"
        ranked.append(
            RankedScore(
                score=score,
                outcome=outcome,
                outcome_label=outcome_label,
                outcome_probability=outcome_probability,
                score_probability=score_probability,
                conditional_bettor_share=conditional_share,
                bonus=bonus,
                base_ev=base_ev,
                exact_score_ev=exact_score_ev,
                total_ev=total_ev,
                payoff_standard_deviation=math.sqrt(payoff_variance),
            )
        )

    # Values tied at the displayed precision prefer the lower-variance payoff.
    ranked.sort(
        key=lambda item: (
            -round(item.total_ev, 2),
            item.payoff_standard_deviation,
            -item.outcome_probability,
            -item.score_probability,
        )
    )
    return ranked


def adjust_bookmaker_exact_score_probabilities(
    rows: list[dict[str, str]],
    score_probabilities: dict[str, float],
    transition: dict[str, float],
) -> dict[str, float]:
    adjusted = dict(score_probabilities)
    draw_retention_factor = transition["draw_retention_factor"]
    home_share = transition["home_share"]
    away_share = transition["away_share"]
    by_score: dict[tuple[int, int], str] = {}
    other_index: str | None = None

    for index, row in enumerate(rows):
        key = str(index)
        if row["score"].strip().lower() == "other":
            other_index = key
            continue
        by_score[(int(row["home_goals"]), int(row["away_goals"]))] = key

    def add_mass(home_goals: int, away_goals: int, mass: float) -> None:
        target = by_score.get((home_goals, away_goals))
        if target is not None:
            adjusted[target] = adjusted.get(target, 0.0) + mass
        elif other_index is not None:
            adjusted[other_index] = adjusted.get(other_index, 0.0) + mass

    for (goals, away_goals), index in by_score.items():
        if goals != away_goals:
            continue
        mass = score_probabilities[index]
        released = mass * (1.0 - draw_retention_factor)
        if released <= 0:
            continue
        adjusted[index] -= released
        add_mass(goals + 1, goals, released * home_share)
        add_mass(goals, goals + 1, released * away_share)

    return adjusted


def adjust_bookmaker_bettor_percentages(
    rows: list[dict[str, str]],
    bettor_percentages: dict[str, float],
    transition: dict[str, float],
) -> dict[str, float]:
    adjusted = dict(bettor_percentages)
    draw_retention_factor = transition["draw_retention_factor"]
    home_share = transition["home_share"]
    away_share = transition["away_share"]
    by_score: dict[tuple[int, int], str] = {}
    other_index: str | None = None

    for index, row in enumerate(rows):
        key = str(index)
        if row["score"].strip().lower() == "other":
            other_index = key
            continue
        by_score[(int(row["home_goals"]), int(row["away_goals"]))] = key

    def add_mass(home_goals: int, away_goals: int, mass: float) -> None:
        target = by_score.get((home_goals, away_goals))
        if target is not None:
            adjusted[target] = adjusted.get(target, 0.0) + mass
        elif other_index is not None:
            adjusted[other_index] = adjusted.get(other_index, 0.0) + mass

    for (goals, away_goals), index in by_score.items():
        if goals != away_goals:
            continue
        mass = bettor_percentages[index]
        released = mass * (1.0 - draw_retention_factor)
        if released <= 0:
            continue
        adjusted[index] -= released
        add_mass(goals + 1, goals, released * home_share)
        add_mass(goals, goals + 1, released * away_share)

    return adjusted


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def group_matches(rows: Iterable[dict[str, str]]) -> dict[tuple[str, str, str], list[dict[str, str]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        key = (row["match"], row["home_team"], row["away_team"])
        grouped.setdefault(key, []).append(row)
    return grouped


def load_game_inputs(
    mpg_path: str | Path,
    probability_path: str | Path,
) -> dict[tuple[str, str], tuple[dict[str, float], dict[str, float], str]]:
    probability_rows = read_csv(probability_path)
    probabilities = {}
    game_stages = {}
    for row in probability_rows:
        key = (normalize_team(row["home_team"]), normalize_team(row["away_team"]))
        probabilities[key] = {
            "home": float(row["home_probability"]),
            "draw": float(row["draw_probability"]),
            "away": float(row["away_probability"]),
        }
        game_stages[key] = row.get("game_stage", "")

    result = {}
    for row in read_csv(mpg_path):
        key = (normalize_team(row["home_team"]), normalize_team(row["away_team"]))
        if key not in probabilities:
            continue
        result[key] = (
            probabilities[key],
            {
                "home": float(row["home_odds"]),
                "draw": float(row["draw_odds"]),
                "away": float(row["away_odds"]),
            },
            game_stages[key],
        )
    return result


def markdown_table(rows: Iterable[RankedScore]) -> str:
    lines = [
        "| Rank | Exact score | Outcome probability | Exact-score probability | "
        "Conditional bettor share | Bonus | Expected bonus | Base EV | Exact-score EV | Total EV |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rank, row in enumerate(rows, start=1):
        lines.append(
            f"| {rank} | {row.outcome_label} {row.score} | "
            f"{row.outcome_probability:.2%} | {row.score_probability:.2%} | "
            f"{row.conditional_bettor_share:.2%} | {row.bonus.nominal_points:.0f} pts | "
            f"{row.bonus.expected_points:.2f} pts | {row.base_ev:.2f} | "
            f"{row.exact_score_ev:.2f} | **{row.total_ev:.2f}** |"
        )
    return "\n".join(lines)


def bettor_share_transfer_variants(mode: str) -> list[tuple[str, bool]]:
    if mode == "off":
        return [("no_transfer", False)]
    if mode == "on":
        return [("transfer", True)]
    if mode == "both":
        return [("no_transfer", False), ("transfer", True)]
    raise ValueError(f"Unknown bettor share transfer mode: {mode}")


def append_odds_log(
    path: str | Path,
    rows: Iterable[dict[str, str]],
    logged_at_utc: str,
    submission_id: str,
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_header = not destination.exists() or destination.stat().st_size == 0
    with destination.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=ODDS_LOG_FIELDS)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "logged_at_utc": logged_at_utc,
                    "submission_id": submission_id,
                    **{field: row[field] for field in ODDS_LOG_FIELDS[2:]},
                }
            )


def ensure_csv_header(path: Path, fieldnames: list[str]) -> None:
    if not path.exists() or path.stat().st_size == 0:
        return
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        existing_fieldnames = reader.fieldnames or []
        if existing_fieldnames == fieldnames:
            return
        rows = list(reader)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def append_prediction_log(
    path: str | Path,
    match: str,
    ranked: list[RankedScore],
    logged_at_utc: str,
    submission_id: str,
    sigma: float,
    bettor_share_transfer: str = "no_transfer",
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ensure_csv_header(destination, PREDICTION_LOG_FIELDS)
    write_header = not destination.exists() or destination.stat().st_size == 0
    with destination.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=PREDICTION_LOG_FIELDS)
        if write_header:
            writer.writeheader()
        for rank, row in enumerate(ranked[:5], start=1):
            writer.writerow(
                {
                    "logged_at_utc": logged_at_utc,
                    "submission_id": submission_id,
                    "match": match,
                    "conditional_share_sigma": sigma,
                    "bettor_share_transfer": bettor_share_transfer,
                    "rank": rank,
                    "score": row.score,
                    "outcome": row.outcome,
                    "outcome_label": row.outcome_label,
                    "outcome_probability": row.outcome_probability,
                    "exact_score_probability": row.score_probability,
                    "conditional_bettor_share": row.conditional_bettor_share,
                    "nominal_bonus_label": row.bonus.nominal_label,
                    "nominal_bonus_points": row.bonus.nominal_points,
                    "expected_bonus_points": row.bonus.expected_points,
                    "base_ev": row.base_ev,
                    "exact_score_ev": row.exact_score_ev,
                    "total_ev": row.total_ev,
                    "payoff_standard_deviation": row.payoff_standard_deviation,
                    "is_best_pick": rank == 1,
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv")
    parser.add_argument("--mpg-file", default=DEFAULT_MPG_FILE)
    parser.add_argument("--probability-file", default=DEFAULT_PROBABILITY_FILE)
    parser.add_argument("--sigma", type=float, default=DEFAULT_CONDITIONAL_SHARE_SIGMA)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--odds-log", default=DEFAULT_ODDS_LOG)
    parser.add_argument("--prediction-log", default=DEFAULT_PREDICTION_LOG)
    parser.add_argument("--submission-id")
    parser.add_argument("--logged-at-utc")
    parser.add_argument(
        "--devig-method",
        choices=["proportional", "power"],
        default=DEFAULT_DEVIG_METHOD,
        help="Bookmaker exact-score margin removal method. Default keeps the old proportional normalization.",
    )
    parser.add_argument(
        "--bettor-share-transfer",
        choices=["off", "on", "both"],
        default="both",
        help=(
            "Whether elimination-game draw bettor shares are transferred to +1 "
            "extra-time winner scores. Default logs and prints both variants."
        ),
    )
    parser.add_argument("--no-log", action="store_true")
    args = parser.parse_args()

    input_rows = read_csv(args.input_csv)
    logged_at_utc = args.logged_at_utc or datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat(timespec="seconds")
    submission_id = args.submission_id or uuid.uuid4().hex

    games = load_game_inputs(args.mpg_file, args.probability_file)
    results = []
    for (match, home_team, away_team), rows in group_matches(input_rows).items():
        key = (normalize_team(home_team), normalize_team(away_team))
        if key not in games:
            raise SystemExit(f"No MPG/probability data found for {match}")
        probabilities, points, game_stage = games[key]
        for variant_label, transfer_bettor_shares in bettor_share_transfer_variants(
            args.bettor_share_transfer
        ):
            ranked = rank_scores(
                rows,
                probabilities,
                points,
                home_team,
                away_team,
                args.sigma,
                args.devig_method,
                game_stage,
                transfer_bettor_shares,
            )
            results.append((match, variant_label, ranked))

    if not args.no_log:
        append_odds_log(args.odds_log, input_rows, logged_at_utc, submission_id)

    for match, variant_label, ranked in results:
        print(f"### {match} ({variant_label})\n")
        print(markdown_table(ranked[: args.top]))
        print(f"\nBest pick: {ranked[0].outcome_label} {ranked[0].score}\n")
        if not args.no_log:
            append_prediction_log(
                args.prediction_log,
                match,
                ranked,
                logged_at_utc,
                submission_id,
                args.sigma,
                variant_label,
            )


if __name__ == "__main__":
    main()
