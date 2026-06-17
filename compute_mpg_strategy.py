#!/usr/bin/env python3
"""Compute the optimal MPG pick strategy from market-implied probabilities.

The MPG odds are point payouts, not decimal betting odds. For each game:

  base_expected_points = outcome_probability * outcome_points

If an exact score is also selected, its expected boost is:

  exact_score_probability * bonus_points

The probability that a score occurs and the share of bettors selecting that
score are different quantities. Exact-score probability remains the calibrated
market-implied score model. MPG bonus tiers instead use a bettor-share estimate:

  bettor weight = score_probability * exact_score_behavior_multiplier
  bettor share = bettor weight / sum(weights within the result outcome)

The denominator includes the outcome-specific out-of-grid "Other" probability
with multiplier 1.0. Multipliers are orientation-neutral: canonical score 2-1
applies to both home 2-1 and away 1-2. They are conservative behavioral
corrections derived from model-versus-injected bettor-share residuals, shrunk
toward 1.0 because the sample is small and displayed shares are rounded.

These multipliers never alter result probabilities or exact-score occurrence
probabilities. They only alter the estimated popularity used to assign MPG
rarity bonus tiers.

The selected strategy is the outcome + exact score pair with the highest total
expected points.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path


DEFAULT_MPG_FILE = "data/mpg/mpg.txt"
DEFAULT_PROBABILITY_FILE = "data/processed/latest_game_probabilities.csv"
DEFAULT_EXACT_SCORE_FILE = "data/processed/latest_exact_score_probabilities_calibrated.csv"
DEFAULT_BETTOR_MULTIPLIER_FILE = "data/mpg/bettor_behavior_exact_score_multipliers.csv"
DEFAULT_OUT = "data/mpg/mpg_optimal_strategy.csv"
DEFAULT_SCORE_EV_OUT = "data/mpg/mpg_score_expected_values.csv"
DEFAULT_HISTORY_DIR = "data/mpg/strategy_snapshots"

TEAM_ALIASES = {
    "Bosnia": "Bosnia & Herzegovina",
    "Cote d'Ivoire": "Ivory Coast",
    "Curacao": "Curaçao",
    "Czechia": "Czech Republic",
    "United States": "USA",
}

OUT_FIELDS = [
    "date",
    "time",
    "home_team",
    "away_team",
    "matched_home_team",
    "matched_away_team",
    "home_probability",
    "draw_probability",
    "away_probability",
    "home_points",
    "draw_points",
    "away_points",
    "home_expected_points",
    "draw_expected_points",
    "away_expected_points",
    "home_best_exact_score",
    "draw_best_exact_score",
    "away_best_exact_score",
    "home_best_exact_score_probability",
    "draw_best_exact_score_probability",
    "away_best_exact_score_probability",
    "home_best_exact_score_model_conditional_probability",
    "draw_best_exact_score_model_conditional_probability",
    "away_best_exact_score_model_conditional_probability",
    "home_best_exact_score_conditional_probability",
    "draw_best_exact_score_conditional_probability",
    "away_best_exact_score_conditional_probability",
    "home_best_exact_bonus_label",
    "draw_best_exact_bonus_label",
    "away_best_exact_bonus_label",
    "home_best_exact_bonus_points",
    "draw_best_exact_bonus_points",
    "away_best_exact_bonus_points",
    "home_exact_bonus_expected_points",
    "draw_exact_bonus_expected_points",
    "away_exact_bonus_expected_points",
    "home_expected_boost_from_exact_score",
    "draw_expected_boost_from_exact_score",
    "away_expected_boost_from_exact_score",
    "home_total_expected_points",
    "draw_total_expected_points",
    "away_total_expected_points",
    "optimal_pick",
    "optimal_exact_score",
    "optimal_exact_bonus_label",
    "optimal_pick_probability",
    "optimal_pick_points",
    "optimal_exact_score_probability",
    "optimal_exact_score_model_conditional_probability",
    "optimal_exact_score_conditional_probability",
    "optimal_exact_bonus_points",
    "optimal_base_expected_points",
    "optimal_exact_bonus_expected_points",
    "optimal_expected_points",
    "second_best_pick",
    "second_best_expected_points",
    "expected_points_edge",
    "base_only_optimal_pick",
    "strategy_changed_by_exact_bonus",
]

SCORE_EV_FIELDS = [
    "date",
    "time",
    "home_team",
    "away_team",
    "matched_home_team",
    "matched_away_team",
    "score",
    "outcome",
    "outcome_label",
    "outcome_probability",
    "score_probability",
    "score_model_conditional_probability",
    "score_conditional_probability",
    "outcome_points",
    "base_expected_points",
    "exact_bonus_label",
    "exact_bonus_points",
    "exact_bonus_expected_points",
    "total_expected_points",
]


def normalize_team(team: str) -> str:
    return TEAM_ALIASES.get(team.strip(), team.strip())


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_bettor_behavior_multipliers(path: str | Path) -> dict[str, float]:
    multipliers: dict[str, float] = {}
    for row in read_csv(path):
        score = row["canonical_score"].strip()
        multiplier = float(row["multiplier"])
        if multiplier <= 0:
            raise ValueError(f"Bettor behavior multiplier for {score} must be positive")
        multipliers[score] = multiplier
    return multipliers


def probability_lookup(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row["home_team"], row["away_team"]): row for row in rows}


def outcome_label(outcome: str, home_team: str, away_team: str) -> str:
    if outcome == "home":
        return home_team
    if outcome == "away":
        return away_team
    return "Draw"


def bonus_for_conditional_probability(probability: float) -> tuple[str, float]:
    if probability > 0.30:
        return "Exact", 20.0
    if probability >= 0.20:
        return "Rare", 30.0
    if probability >= 0.05:
        return "Tres rare", 50.0
    if probability >= 0.005:
        return "Mega rare", 70.0
    return "Ultra rare", 100.0


def exact_score_lookup(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row["home_team"], row["away_team"]): row for row in rows}


def score_outcome(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if home_goals < away_goals:
        return "away"
    return "draw"


def canonical_score(home_goals: int, away_goals: int) -> str:
    if home_goals == away_goals:
        return f"{home_goals}-{away_goals}"
    return f"{max(home_goals, away_goals)}-{min(home_goals, away_goals)}"


def other_probability_for_outcome(exact_row: dict[str, str], outcome: str) -> float:
    column = (
        f"other_{outcome}_win_probability"
        if outcome in {"home", "away"}
        else "other_draw_probability"
    )
    return float(exact_row[column])


def bettor_share_estimates(
    exact_row: dict[str, str],
    outcome: str,
    multipliers: dict[str, float],
) -> dict[str, dict[str, float]]:
    """Return raw model conditionals and behavior-adjusted bettor shares.

    Explicit score weights are multiplied by the orientation-neutral behavior
    factor and renormalized with the outcome-specific Other mass left at 1.0.
    Consequently, adjusted explicit shares plus adjusted Other share sum to 1.
    """
    scores: list[tuple[int, int, float]] = []
    for home_goals in range(5):
        for away_goals in range(5):
            if score_outcome(home_goals, away_goals) != outcome:
                continue
            probability = float(exact_row[f"score_{home_goals}_{away_goals}_probability"])
            scores.append((home_goals, away_goals, probability))

    other_probability = other_probability_for_outcome(exact_row, outcome)
    model_total = sum(probability for _, _, probability in scores) + other_probability
    weighted_total = other_probability + sum(
        probability * multipliers.get(canonical_score(home_goals, away_goals), 1.0)
        for home_goals, away_goals, probability in scores
    )
    if model_total <= 0 or weighted_total <= 0:
        raise ValueError(f"Cannot calculate bettor shares for empty {outcome} distribution")

    return {
        f"{home_goals}-{away_goals}": {
            "model_conditional_probability": probability / model_total,
            "conditional_probability": (
                probability
                * multipliers.get(canonical_score(home_goals, away_goals), 1.0)
                / weighted_total
            ),
        }
        for home_goals, away_goals, probability in scores
    }


def best_exact_score_for_outcome(
    exact_row: dict[str, str],
    outcome: str,
    bettor_multipliers: dict[str, float],
) -> dict[str, str | float]:
    bettor_shares = bettor_share_estimates(exact_row, outcome, bettor_multipliers)
    best: dict[str, str | float] | None = None

    for home_goals in range(5):
        for away_goals in range(5):
            if score_outcome(home_goals, away_goals) != outcome:
                continue
            score = f"{home_goals}-{away_goals}"
            score_probability = float(exact_row[f"score_{home_goals}_{away_goals}_probability"])
            model_conditional_probability = bettor_shares[score]["model_conditional_probability"]
            conditional_probability = bettor_shares[score]["conditional_probability"]
            bonus_label, bonus_points = bonus_for_conditional_probability(conditional_probability)
            bonus_expected_points = score_probability * bonus_points

            candidate = {
                "score": score,
                "score_probability": score_probability,
                "model_conditional_probability": model_conditional_probability,
                "conditional_probability": conditional_probability,
                "bonus_label": bonus_label,
                "bonus_points": bonus_points,
                "bonus_expected_points": bonus_expected_points,
            }
            if best is None or float(candidate["bonus_expected_points"]) > float(best["bonus_expected_points"]):
                best = candidate

    if best is None:
        raise ValueError(f"No exact-score candidates found for outcome {outcome}")
    return best


def compute_strategy(
    mpg_rows: list[dict[str, str]],
    probability_rows: list[dict[str, str]],
    exact_score_rows: list[dict[str, str]],
    bettor_multipliers: dict[str, float] | None = None,
) -> list[dict[str, str | float]]:
    bettor_multipliers = (
        load_bettor_behavior_multipliers(DEFAULT_BETTOR_MULTIPLIER_FILE)
        if bettor_multipliers is None
        else bettor_multipliers
    )
    probabilities = probability_lookup(probability_rows)
    exact_scores = exact_score_lookup(exact_score_rows)
    output_rows: list[dict[str, str | float]] = []
    missing: list[tuple[str, str]] = []

    for mpg_row in mpg_rows:
        matched_home = normalize_team(mpg_row["home_team"])
        matched_away = normalize_team(mpg_row["away_team"])
        probability_row = probabilities.get((matched_home, matched_away))
        exact_score_row = exact_scores.get((matched_home, matched_away))
        if probability_row is None or exact_score_row is None:
            missing.append((mpg_row["home_team"], mpg_row["away_team"]))
            continue

        home_probability = float(probability_row["home_probability"])
        draw_probability = float(probability_row["draw_probability"])
        away_probability = float(probability_row["away_probability"])

        home_points = float(mpg_row["home_odds"])
        draw_points = float(mpg_row["draw_odds"])
        away_points = float(mpg_row["away_odds"])

        base_expected = {
            "home": home_probability * home_points,
            "draw": draw_probability * draw_points,
            "away": away_probability * away_points,
        }
        exact = {
            "home": best_exact_score_for_outcome(exact_score_row, "home", bettor_multipliers),
            "draw": best_exact_score_for_outcome(exact_score_row, "draw", bettor_multipliers),
            "away": best_exact_score_for_outcome(exact_score_row, "away", bettor_multipliers),
        }

        candidates = []
        for outcome, probability, points in [
            ("home", home_probability, home_points),
            ("draw", draw_probability, draw_points),
            ("away", away_probability, away_points),
        ]:
            exact_bonus_expected_points = float(exact[outcome]["bonus_expected_points"])
            total_expected_points = base_expected[outcome] + exact_bonus_expected_points
            candidates.append(
                {
                    "outcome": outcome,
                    "probability": probability,
                    "points": points,
                    "base_expected_points": base_expected[outcome],
                    "total_expected_points": total_expected_points,
                    **exact[outcome],
                }
            )

        candidates.sort(key=lambda item: float(item["total_expected_points"]), reverse=True)
        best = candidates[0]
        second = candidates[1]
        base_only_best = max(base_expected, key=base_expected.get)

        output_rows.append(
            {
                "date": mpg_row["date"],
                "time": mpg_row["time"],
                "home_team": mpg_row["home_team"],
                "away_team": mpg_row["away_team"],
                "matched_home_team": matched_home,
                "matched_away_team": matched_away,
                "home_probability": home_probability,
                "draw_probability": draw_probability,
                "away_probability": away_probability,
                "home_points": home_points,
                "draw_points": draw_points,
                "away_points": away_points,
                "home_expected_points": home_probability * home_points,
                "draw_expected_points": draw_probability * draw_points,
                "away_expected_points": away_probability * away_points,
                "home_best_exact_score": exact["home"]["score"],
                "draw_best_exact_score": exact["draw"]["score"],
                "away_best_exact_score": exact["away"]["score"],
                "home_best_exact_score_probability": exact["home"]["score_probability"],
                "draw_best_exact_score_probability": exact["draw"]["score_probability"],
                "away_best_exact_score_probability": exact["away"]["score_probability"],
                "home_best_exact_score_model_conditional_probability": exact["home"]["model_conditional_probability"],
                "draw_best_exact_score_model_conditional_probability": exact["draw"]["model_conditional_probability"],
                "away_best_exact_score_model_conditional_probability": exact["away"]["model_conditional_probability"],
                "home_best_exact_score_conditional_probability": exact["home"]["conditional_probability"],
                "draw_best_exact_score_conditional_probability": exact["draw"]["conditional_probability"],
                "away_best_exact_score_conditional_probability": exact["away"]["conditional_probability"],
                "home_best_exact_bonus_label": exact["home"]["bonus_label"],
                "draw_best_exact_bonus_label": exact["draw"]["bonus_label"],
                "away_best_exact_bonus_label": exact["away"]["bonus_label"],
                "home_best_exact_bonus_points": exact["home"]["bonus_points"],
                "draw_best_exact_bonus_points": exact["draw"]["bonus_points"],
                "away_best_exact_bonus_points": exact["away"]["bonus_points"],
                "home_exact_bonus_expected_points": exact["home"]["bonus_expected_points"],
                "draw_exact_bonus_expected_points": exact["draw"]["bonus_expected_points"],
                "away_exact_bonus_expected_points": exact["away"]["bonus_expected_points"],
                "home_expected_boost_from_exact_score": exact["home"]["bonus_expected_points"],
                "draw_expected_boost_from_exact_score": exact["draw"]["bonus_expected_points"],
                "away_expected_boost_from_exact_score": exact["away"]["bonus_expected_points"],
                "home_total_expected_points": base_expected["home"] + float(exact["home"]["bonus_expected_points"]),
                "draw_total_expected_points": base_expected["draw"] + float(exact["draw"]["bonus_expected_points"]),
                "away_total_expected_points": base_expected["away"] + float(exact["away"]["bonus_expected_points"]),
                "optimal_pick": outcome_label(str(best["outcome"]), mpg_row["home_team"], mpg_row["away_team"]),
                "optimal_exact_score": best["score"],
                "optimal_exact_bonus_label": best["bonus_label"],
                "optimal_pick_probability": best["probability"],
                "optimal_pick_points": best["points"],
                "optimal_exact_score_probability": best["score_probability"],
                "optimal_exact_score_model_conditional_probability": best["model_conditional_probability"],
                "optimal_exact_score_conditional_probability": best["conditional_probability"],
                "optimal_exact_bonus_points": best["bonus_points"],
                "optimal_base_expected_points": best["base_expected_points"],
                "optimal_exact_bonus_expected_points": best["bonus_expected_points"],
                "optimal_expected_points": best["total_expected_points"],
                "second_best_pick": outcome_label(str(second["outcome"]), mpg_row["home_team"], mpg_row["away_team"]),
                "second_best_expected_points": second["total_expected_points"],
                "expected_points_edge": float(best["total_expected_points"]) - float(second["total_expected_points"]),
                "base_only_optimal_pick": outcome_label(base_only_best, mpg_row["home_team"], mpg_row["away_team"]),
                "strategy_changed_by_exact_bonus": outcome_label(str(best["outcome"]), mpg_row["home_team"], mpg_row["away_team"])
                != outcome_label(base_only_best, mpg_row["home_team"], mpg_row["away_team"]),
            }
        )

    if missing:
        missing_text = "\n".join(f"  {home} vs {away}" for home, away in missing)
        raise SystemExit(f"Could not match {len(missing)} MPG games to probability rows:\n{missing_text}")

    return output_rows


def compute_score_expected_values(
    mpg_rows: list[dict[str, str]],
    probability_rows: list[dict[str, str]],
    exact_score_rows: list[dict[str, str]],
    bettor_multipliers: dict[str, float] | None = None,
) -> list[dict[str, str | float]]:
    bettor_multipliers = (
        load_bettor_behavior_multipliers(DEFAULT_BETTOR_MULTIPLIER_FILE)
        if bettor_multipliers is None
        else bettor_multipliers
    )
    probabilities = probability_lookup(probability_rows)
    exact_scores = exact_score_lookup(exact_score_rows)
    output_rows: list[dict[str, str | float]] = []
    missing: list[tuple[str, str]] = []

    for mpg_row in mpg_rows:
        matched_home = normalize_team(mpg_row["home_team"])
        matched_away = normalize_team(mpg_row["away_team"])
        probability_row = probabilities.get((matched_home, matched_away))
        exact_score_row = exact_scores.get((matched_home, matched_away))
        if probability_row is None or exact_score_row is None:
            missing.append((mpg_row["home_team"], mpg_row["away_team"]))
            continue

        outcome_probabilities = {
            "home": float(probability_row["home_probability"]),
            "draw": float(probability_row["draw_probability"]),
            "away": float(probability_row["away_probability"]),
        }
        outcome_points = {
            "home": float(mpg_row["home_odds"]),
            "draw": float(mpg_row["draw_odds"]),
            "away": float(mpg_row["away_odds"]),
        }
        bettor_shares = {
            outcome: bettor_share_estimates(exact_score_row, outcome, bettor_multipliers)
            for outcome in ("home", "draw", "away")
        }

        for home_goals in range(5):
            for away_goals in range(5):
                outcome = score_outcome(home_goals, away_goals)
                score = f"{home_goals}-{away_goals}"
                score_probability = float(exact_score_row[f"score_{home_goals}_{away_goals}_probability"])
                outcome_probability = outcome_probabilities[outcome]
                model_conditional_probability = bettor_shares[outcome][score]["model_conditional_probability"]
                conditional_probability = bettor_shares[outcome][score]["conditional_probability"]
                bonus_label, bonus_points = bonus_for_conditional_probability(conditional_probability)
                base_expected_points = outcome_probability * outcome_points[outcome]
                exact_bonus_expected_points = score_probability * bonus_points

                output_rows.append(
                    {
                        "date": mpg_row["date"],
                        "time": mpg_row["time"],
                        "home_team": mpg_row["home_team"],
                        "away_team": mpg_row["away_team"],
                        "matched_home_team": matched_home,
                        "matched_away_team": matched_away,
                        "score": score,
                        "outcome": outcome,
                        "outcome_label": outcome_label(outcome, mpg_row["home_team"], mpg_row["away_team"]),
                        "outcome_probability": outcome_probability,
                        "score_probability": score_probability,
                        "score_model_conditional_probability": model_conditional_probability,
                        "score_conditional_probability": conditional_probability,
                        "outcome_points": outcome_points[outcome],
                        "base_expected_points": base_expected_points,
                        "exact_bonus_label": bonus_label,
                        "exact_bonus_points": bonus_points,
                        "exact_bonus_expected_points": exact_bonus_expected_points,
                        "total_expected_points": base_expected_points + exact_bonus_expected_points,
                    }
                )

    if missing:
        missing_text = "\n".join(f"  {home} vs {away}" for home, away in missing)
        raise SystemExit(f"Could not match {len(missing)} MPG games to probability rows:\n{missing_text}")

    return output_rows


def write_rows(
    rows: list[dict[str, str | float]],
    path: str | Path,
    *,
    overwrite: bool = True,
) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with out_path.open(mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_score_ev_rows(
    rows: list[dict[str, str | float]],
    path: str | Path,
    *,
    overwrite: bool = True,
) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with out_path.open(mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCORE_EV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def strategy_snapshot_paths(
    history_dir: str | Path,
    now: datetime | None = None,
) -> tuple[Path, Path, Path]:
    captured_at = now or datetime.now(UTC)
    timestamp = captured_at.strftime("%Y%m%dT%H%M%SZ")
    directory = Path(history_dir) / captured_at.strftime("%Y") / captured_at.strftime("%m")
    return (
        directory / f"mpg_optimal_strategy_{timestamp}.csv",
        directory / f"mpg_score_expected_values_{timestamp}.csv",
        directory / f"metadata_{timestamp}.json",
    )


def write_strategy_snapshot(
    strategy_rows: list[dict[str, str | float]],
    score_ev_rows: list[dict[str, str | float]],
    history_dir: str | Path,
    inputs: dict[str, str],
    now: datetime | None = None,
) -> tuple[Path, Path, Path]:
    captured_at = now or datetime.now(UTC)
    strategy_path, score_ev_path, metadata_path = strategy_snapshot_paths(
        history_dir, captured_at
    )
    for path in (strategy_path, score_ev_path, metadata_path):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite immutable strategy snapshot: {path}")

    write_rows(strategy_rows, strategy_path, overwrite=False)
    write_score_ev_rows(score_ev_rows, score_ev_path, overwrite=False)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with metadata_path.open("x", encoding="utf-8") as file:
        json.dump(
            {
                "captured_at_utc": captured_at.isoformat(),
                "strategy_snapshot": str(strategy_path),
                "score_ev_snapshot": str(score_ev_path),
                "inputs": inputs,
                "games": len(strategy_rows),
                "score_ev_rows": len(score_ev_rows),
            },
            file,
            indent=2,
            sort_keys=True,
        )
        file.write("\n")
    return strategy_path, score_ev_path, metadata_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mpg-file", default=DEFAULT_MPG_FILE)
    parser.add_argument("--probability-file", default=DEFAULT_PROBABILITY_FILE)
    parser.add_argument("--exact-score-file", default=DEFAULT_EXACT_SCORE_FILE)
    parser.add_argument("--bettor-multiplier-file", default=DEFAULT_BETTOR_MULTIPLIER_FILE)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--score-ev-out", default=DEFAULT_SCORE_EV_OUT)
    parser.add_argument(
        "--history-dir",
        default=DEFAULT_HISTORY_DIR,
        help="Directory for immutable timestamped strategy and EV snapshots.",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Do not write an immutable timestamped strategy snapshot.",
    )
    args = parser.parse_args()

    mpg_rows = read_csv(args.mpg_file)
    probability_rows = read_csv(args.probability_file)
    exact_score_rows = read_csv(args.exact_score_file)
    bettor_multipliers = load_bettor_behavior_multipliers(args.bettor_multiplier_file)
    strategy_rows = compute_strategy(
        mpg_rows, probability_rows, exact_score_rows, bettor_multipliers
    )
    score_ev_rows = compute_score_expected_values(
        mpg_rows, probability_rows, exact_score_rows, bettor_multipliers
    )
    snapshot_paths = None
    if not args.no_history:
        try:
            snapshot_paths = write_strategy_snapshot(
                strategy_rows,
                score_ev_rows,
                args.history_dir,
                {
                    "mpg_file": args.mpg_file,
                    "probability_file": args.probability_file,
                    "exact_score_file": args.exact_score_file,
                    "bettor_multiplier_file": args.bettor_multiplier_file,
                },
            )
        except FileExistsError as exc:
            raise SystemExit(str(exc)) from exc
    write_rows(strategy_rows, args.out)
    write_score_ev_rows(score_ev_rows, args.score_ev_out)

    total_expected_points = sum(float(row["optimal_expected_points"]) for row in strategy_rows)
    changed_count = sum(bool(row["strategy_changed_by_exact_bonus"]) for row in strategy_rows)
    print(f"MPG games processed: {len(strategy_rows)}")
    print(f"Score EV rows written: {len(score_ev_rows)}")
    print(f"Total expected points: {total_expected_points:.2f}")
    print(f"Strategies changed by exact-score bonus: {changed_count}")
    print(f"Saved strategy: {args.out}")
    print(f"Saved score EV table: {args.score_ev_out}")
    if snapshot_paths is not None:
        print(f"Saved immutable strategy snapshot: {snapshot_paths[0]}")
        print(f"Saved immutable score EV snapshot: {snapshot_paths[1]}")
        print(f"Saved snapshot metadata: {snapshot_paths[2]}")


if __name__ == "__main__":
    main()
