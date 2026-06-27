#!/usr/bin/env python3
"""Simulate transcribed picks versus bookmaker-injected top picks."""

from __future__ import annotations

import csv
import datetime as dt
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bookmaker_injected_strategy
from odds_pipeline.processing import normalize_implied_probabilities

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import analyze_bookmaker_injected_results as simulation


DEFAULT_MANU_FILE = ROOT / "data/mpg/manu_pronos.csv"
DEFAULT_NATHAN_FILE = ROOT / "data/mpg/nathan_pronos.csv"
DEFAULT_ODDS_LOG = ROOT / "data/bookmaker_injected/bookmaker_score_odds.csv"
DEFAULT_PREDICTION_LOG = ROOT / "data/bookmaker_injected/expected_mpg_top5.csv"
DEFAULT_COMPLETED_FILE = ROOT / "data/mpg/completed_games.csv"
DEFAULT_MPG_FILE = ROOT / "data/mpg/mpg.txt"
DEFAULT_OUT_DIR = ROOT / "data/analysis/strategy_simulations/manu_vs_bookmaker_injected"
DEFAULT_ROLLOUTS = 200_000
DEFAULT_SEED = 20260626

SUMMARY_FIELDS = [
    "strategy",
    "games",
    "realized_points",
    "expected_points",
    "simulation_mean",
    "simulation_std",
    "p05",
    "p50",
    "p95",
    "realized_percentile",
]

MANU_RESULT_FIELDS = [
    "commence_time",
    "match",
    "selected_score",
    "actual_score",
    "outcome_correct",
    "exact_score_correct",
    "base_points",
    "exact_bonus_points",
    "realized_points",
    "expected_points",
    "realized_minus_expected",
    "source_submission_id",
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


def normalize_team(team: str) -> str:
    return bookmaker_injected_strategy.normalize_team(team)


def match_key(home_team: str, away_team: str) -> tuple[str, str]:
    return normalize_team(home_team), normalize_team(away_team)


def score_outcome(score: str) -> str:
    home_goals, away_goals = (int(part) for part in score.split("-"))
    return bookmaker_injected_strategy.score_outcome(home_goals, away_goals)


def completed_lookup(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {
        match_key(row["home_team"], row["away_team"]): row
        for row in rows
    }


def grouped_submissions(
    odds_rows: list[dict[str, str]],
) -> dict[tuple[str, str, str], list[dict[str, str]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in odds_rows:
        grouped.setdefault(
            (row["submission_id"], row["match"], row["logged_at_utc"]),
            [],
        ).append(row)
    return grouped


def prediction_probabilities(
    rows: list[dict[str, str]],
) -> dict[tuple[str, str], dict[str, float]]:
    probabilities: dict[tuple[str, str], dict[str, float]] = {}
    for row in rows:
        key = (row["submission_id"], row["match"])
        probabilities.setdefault(key, {})
        probabilities[key][row["outcome"]] = float(row["outcome_probability"])
    return probabilities


def prediction_sigmas(rows: list[dict[str, str]]) -> dict[tuple[str, str], float]:
    return {
        (row["submission_id"], row["match"]): float(
            row.get("conditional_share_sigma", "0.01") or "0.01"
        )
        for row in rows
    }


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
    return {outcome: value / total for outcome, value in shares.items()}


def complete_outcome_probabilities(
    odds_rows: list[dict[str, str]],
    logged_probabilities: dict[str, float],
) -> dict[str, float]:
    probabilities = dict(logged_probabilities)
    known_total = sum(probabilities.values())
    if known_total > 1.0:
        return {
            outcome: probabilities.get(outcome, 0.0) / known_total
            for outcome in ("home", "draw", "away")
        }

    missing = [
        outcome for outcome in ("home", "draw", "away") if outcome not in probabilities
    ]
    if not missing:
        return probabilities

    fallback = outcome_shares_from_score_odds(odds_rows)
    fallback_total = sum(fallback[outcome] for outcome in missing)
    remaining = max(0.0, 1.0 - known_total)
    for outcome in missing:
        probabilities[outcome] = (
            remaining / len(missing)
            if fallback_total <= 0
            else remaining * fallback[outcome] / fallback_total
        )
    return probabilities


def latest_pre_kickoff_submission(
    submissions: dict[tuple[str, str, str], list[dict[str, str]]],
    home_team: str,
    away_team: str,
    commence_time: str,
) -> tuple[tuple[str, str, str], list[dict[str, str]]] | None:
    key = match_key(home_team, away_team)
    kickoff = parse_utc(commence_time)
    candidates = []
    for submission_key, rows in submissions.items():
        first = rows[0]
        if match_key(first["home_team"], first["away_team"]) != key:
            continue
        if parse_utc(first["logged_at_utc"]) < kickoff:
            candidates.append((submission_key, rows))
    if not candidates:
        return None
    candidates.sort(key=lambda item: parse_utc(item[0][2]))
    return candidates[-1]


def ranked_score_lookup(
    odds_rows: list[dict[str, str]],
    outcome_probabilities: dict[str, float],
    outcome_points: dict[str, float],
    home_team: str,
    away_team: str,
    sigma: float,
) -> dict[str, bookmaker_injected_strategy.RankedScore]:
    ranked = bookmaker_injected_strategy.rank_scores(
        odds_rows,
        outcome_probabilities,
        outcome_points,
        home_team,
        away_team,
        sigma=sigma,
    )
    return {row.score: row for row in ranked}


def build_transcribed_picks(
    rows: list[dict[str, str]],
    prediction_field: str,
    completed_rows: list[dict[str, str]],
    odds_rows: list[dict[str, str]],
    prediction_rows: list[dict[str, str]],
) -> list[simulation.ScoredPick]:
    completed = completed_lookup(completed_rows)
    submissions = grouped_submissions(odds_rows)
    probabilities_by_submission = prediction_probabilities(prediction_rows)
    sigmas = prediction_sigmas(prediction_rows)
    picks: list[simulation.ScoredPick] = []

    for row in rows:
        key = match_key(row["home_team"], row["away_team"])
        completed_row = completed.get(key)
        if completed_row is None:
            raise ValueError(f"No completed game found for {row['home_team']} vs {row['away_team']}")
        latest = latest_pre_kickoff_submission(
            submissions,
            row["home_team"],
            row["away_team"],
            completed_row["commence_time"],
        )
        if latest is None:
            raise ValueError(f"No pre-kickoff odds submission for {row['home_team']} vs {row['away_team']}")
        submission_key, submission_rows = latest
        submission_id, match, _ = submission_key
        outcome_probabilities = complete_outcome_probabilities(
            submission_rows,
            probabilities_by_submission.get((submission_id, match), {}),
        )
        sigma = sigmas.get(
            (submission_id, match),
            bookmaker_injected_strategy.DEFAULT_CONDITIONAL_SHARE_SIGMA,
        )
        selected_score = row[prediction_field]
        selected_outcome = score_outcome(selected_score)
        outcome_points = {
            "home": 0.0,
            "draw": 0.0,
            "away": 0.0,
        }
        outcome_points[selected_outcome] = float(row["mpg_points"])
        ranked_by_score = ranked_score_lookup(
            submission_rows,
            outcome_probabilities,
            outcome_points,
            row["home_team"],
            row["away_team"],
            sigma,
        )
        actual_score = completed_row["final_score"]
        outcome_correct = selected_outcome == score_outcome(actual_score)
        exact_score_correct = selected_score == actual_score
        realized_points = float(row["recorded_points"])
        exact_bonus_points = max(0.0, realized_points - float(row["mpg_points"])) if exact_score_correct else 0.0
        ranked = ranked_by_score.get(selected_score)
        if ranked is None:
            if exact_score_correct:
                raise ValueError(
                    f"Exact winning score is missing bookmaker odds for {row['home_team']} vs {row['away_team']} {selected_score}"
                )
            outcome_probability = outcome_probabilities[selected_outcome]
            exact_score_probability = 0.0
            conditional_bettor_share = 0.0
            expected_points = outcome_probability * float(row["mpg_points"])
        else:
            outcome_probability = ranked.outcome_probability
            exact_score_probability = ranked.score_probability
            conditional_bettor_share = ranked.conditional_bettor_share
            expected_points = ranked.total_ev
        picks.append(
            simulation.ScoredPick(
                match=f"{completed_row['home_team']} vs {completed_row['away_team']}",
                commence_time=completed_row["commence_time"],
                selected_score=selected_score,
                actual_score=actual_score,
                outcome_probability=outcome_probability,
                exact_score_probability=exact_score_probability,
                conditional_bettor_share=conditional_bettor_share,
                conditional_share_sigma=sigma,
                base_points=float(row["mpg_points"]),
                expected_points=expected_points,
                outcome_correct=outcome_correct,
                exact_score_correct=exact_score_correct,
                exact_bonus_points=exact_bonus_points,
                realized_points=realized_points,
            )
        )

    return picks


def build_manu_picks(
    manu_rows: list[dict[str, str]],
    completed_rows: list[dict[str, str]],
    odds_rows: list[dict[str, str]],
    prediction_rows: list[dict[str, str]],
) -> list[simulation.ScoredPick]:
    return build_transcribed_picks(
        manu_rows,
        "manu_prediction",
        completed_rows,
        odds_rows,
        prediction_rows,
    )


def build_bookmaker_picks_from_odds(
    manu_picks: list[simulation.ScoredPick],
    completed_rows: list[dict[str, str]],
    odds_rows: list[dict[str, str]],
    prediction_rows: list[dict[str, str]],
    mpg_rows: list[dict[str, str]],
) -> list[simulation.ScoredPick]:
    completed = completed_lookup(completed_rows)
    submissions = grouped_submissions(odds_rows)
    probabilities_by_submission = prediction_probabilities(prediction_rows)
    sigmas = prediction_sigmas(prediction_rows)
    points = simulation.mpg_points_lookup(mpg_rows)
    wanted_keys = {(pick.commence_time, pick.match) for pick in manu_picks}
    picks: list[simulation.ScoredPick] = []

    for completed_row in sorted(completed_rows, key=lambda row: row["commence_time"]):
        match = f"{completed_row['home_team']} vs {completed_row['away_team']}"
        if (completed_row["commence_time"], match) not in wanted_keys:
            continue

        key = match_key(completed_row["home_team"], completed_row["away_team"])
        if key not in completed:
            raise ValueError(f"No completed game found for {match}")
        if key not in points:
            raise ValueError(f"No MPG points found for {match}")

        latest = latest_pre_kickoff_submission(
            submissions,
            completed_row["home_team"],
            completed_row["away_team"],
            completed_row["commence_time"],
        )
        if latest is None:
            raise ValueError(f"No pre-kickoff odds submission for {match}")

        submission_key, submission_rows = latest
        submission_id, submission_match, _ = submission_key
        outcome_probabilities = complete_outcome_probabilities(
            submission_rows,
            probabilities_by_submission.get((submission_id, submission_match), {}),
        )
        sigma = sigmas.get(
            (submission_id, submission_match),
            bookmaker_injected_strategy.DEFAULT_CONDITIONAL_SHARE_SIGMA,
        )
        ranked = bookmaker_injected_strategy.rank_scores(
            submission_rows,
            outcome_probabilities,
            points[key],
            completed_row["home_team"],
            completed_row["away_team"],
            sigma=sigma,
        )
        if not ranked:
            raise ValueError(f"No bookmaker-injected candidates for {match}")

        prediction = ranked[0]
        actual_score = completed_row["final_score"]
        outcome_correct = prediction.outcome == score_outcome(actual_score)
        exact_score_correct = prediction.score == actual_score
        exact_bonus_points = (
            prediction.bonus.nominal_points if exact_score_correct else 0.0
        )
        realized_points = (
            points[key][prediction.outcome] + exact_bonus_points
            if outcome_correct
            else 0.0
        )
        picks.append(
            simulation.ScoredPick(
                match=match,
                commence_time=completed_row["commence_time"],
                selected_score=prediction.score,
                actual_score=actual_score,
                outcome_probability=prediction.outcome_probability,
                exact_score_probability=prediction.score_probability,
                conditional_bettor_share=prediction.conditional_bettor_share,
                conditional_share_sigma=sigma,
                base_points=points[key][prediction.outcome],
                expected_points=prediction.total_ev,
                outcome_correct=outcome_correct,
                exact_score_correct=exact_score_correct,
                exact_bonus_points=exact_bonus_points,
                realized_points=realized_points,
            )
        )

    if len(picks) != len(manu_picks):
        raise ValueError(
            f"Bookmaker picks cover {len(picks)} games, Manu covers {len(manu_picks)}"
        )
    return picks


def build_random_player_games_from_odds(
    manu_picks: list[simulation.ScoredPick],
    completed_rows: list[dict[str, str]],
    odds_rows: list[dict[str, str]],
    prediction_rows: list[dict[str, str]],
    mpg_rows: list[dict[str, str]],
) -> list[simulation.RandomGame]:
    submissions = grouped_submissions(odds_rows)
    probabilities_by_submission = prediction_probabilities(prediction_rows)
    sigmas = prediction_sigmas(prediction_rows)
    points = simulation.mpg_points_lookup(mpg_rows)
    wanted_keys = {(pick.commence_time, pick.match) for pick in manu_picks}
    games: list[simulation.RandomGame] = []

    for completed_row in sorted(completed_rows, key=lambda row: row["commence_time"]):
        match = f"{completed_row['home_team']} vs {completed_row['away_team']}"
        if (completed_row["commence_time"], match) not in wanted_keys:
            continue

        key = match_key(completed_row["home_team"], completed_row["away_team"])
        if key not in points:
            raise ValueError(f"No MPG points found for {match}")

        latest = latest_pre_kickoff_submission(
            submissions,
            completed_row["home_team"],
            completed_row["away_team"],
            completed_row["commence_time"],
        )
        if latest is None:
            raise ValueError(f"No pre-kickoff odds submission for {match}")

        submission_key, submission_rows = latest
        submission_id, submission_match, _ = submission_key
        outcome_probabilities = complete_outcome_probabilities(
            submission_rows,
            probabilities_by_submission.get((submission_id, submission_match), {}),
        )
        sigma = sigmas.get(
            (submission_id, submission_match),
            bookmaker_injected_strategy.DEFAULT_CONDITIONAL_SHARE_SIGMA,
        )
        games.append(
            simulation.build_random_game(
                completed_row,
                submission_rows,
                outcome_probabilities,
                points[key],
                sigma,
            )
        )

    if len(games) != len(manu_picks):
        raise ValueError(
            f"Random-player games cover {len(games)} games, Manu covers {len(manu_picks)}"
        )
    return games


def summarize(
    strategy: str,
    picks: list[simulation.ScoredPick],
    totals: np.ndarray,
) -> dict[str, object]:
    realized = sum(pick.realized_points for pick in picks)
    return {
        "strategy": strategy,
        "games": len(picks),
        "realized_points": realized,
        "expected_points": sum(pick.expected_points for pick in picks),
        "simulation_mean": float(totals.mean()),
        "simulation_std": float(totals.std()),
        "p05": float(np.quantile(totals, 0.05)),
        "p50": float(np.quantile(totals, 0.50)),
        "p95": float(np.quantile(totals, 0.95)),
        "realized_percentile": float((totals <= realized).mean()),
    }


def summarize_random_player(
    games: list[simulation.RandomGame],
    totals: np.ndarray,
) -> dict[str, object]:
    realized = simulation.random_player_realized_points(games)
    return {
        "strategy": "random_player_by_bettor_share",
        "games": len(games),
        "realized_points": realized,
        "expected_points": simulation.random_player_expected_points(games),
        "simulation_mean": float(totals.mean()),
        "simulation_std": float(totals.std()),
        "p05": float(np.quantile(totals, 0.05)),
        "p50": float(np.quantile(totals, 0.50)),
        "p95": float(np.quantile(totals, 0.95)),
        "realized_percentile": float((totals <= realized).mean()),
    }


def result_rows(picks: list[simulation.ScoredPick], source: str) -> list[dict[str, object]]:
    rows = simulation.result_rows(picks)
    for row in rows:
        row["source"] = source
    return rows


def write_plot(
    path: str | Path,
    manu_totals: np.ndarray,
    manu_summary: dict[str, object],
    nathan_totals: np.ndarray,
    nathan_summary: dict[str, object],
    bookmaker_totals: np.ndarray,
    bookmaker_summary: dict[str, object],
    random_totals: np.ndarray,
    random_summary: dict[str, object],
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpp-matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 6))
    minimum = min(
        float(manu_totals.min()),
        float(nathan_totals.min()),
        float(bookmaker_totals.min()),
        float(random_totals.min()),
    )
    maximum = max(
        float(manu_totals.max()),
        float(nathan_totals.max()),
        float(bookmaker_totals.max()),
        float(random_totals.max()),
    )
    bins = np.linspace(minimum, maximum, 45)
    ax.hist(
        random_totals,
        bins=bins,
        density=True,
        alpha=0.38,
        color="#2ca02c",
        label=(
            "Random "
            f"mean={float(random_summary['simulation_mean']):.1f}, "
            f"pct={100 * float(random_summary['realized_percentile']):.1f}%"
        ),
    )
    ax.hist(
        bookmaker_totals,
        bins=bins,
        density=True,
        alpha=0.46,
        color="#1f77b4",
        label=(
            "Bookmaker top-1 "
            f"mean={float(bookmaker_summary['simulation_mean']):.1f}, "
            f"pct={100 * float(bookmaker_summary['realized_percentile']):.1f}%"
        ),
    )
    ax.hist(
        manu_totals,
        bins=bins,
        density=True,
        alpha=0.42,
        color="#ff7f0e",
        label=(
            "Manu "
            f"mean={float(manu_summary['simulation_mean']):.1f}, "
            f"pct={100 * float(manu_summary['realized_percentile']):.1f}%"
        ),
    )
    ax.hist(
        nathan_totals,
        bins=bins,
        density=True,
        alpha=0.38,
        color="#9467bd",
        label=(
            "Nathan "
            f"mean={float(nathan_summary['simulation_mean']):.1f}, "
            f"pct={100 * float(nathan_summary['realized_percentile']):.1f}%"
        ),
    )
    ax.axvline(
        float(random_summary["realized_points"]),
        color="#2ca02c",
        linewidth=2,
        linestyle="--",
        label=f"Random realized={float(random_summary['realized_points']):.0f}",
    )
    ax.axvline(
        float(bookmaker_summary["realized_points"]),
        color="#1f77b4",
        linewidth=2,
        linestyle="--",
        label=f"Bookmaker realized={float(bookmaker_summary['realized_points']):.0f}",
    )
    ax.axvline(
        float(manu_summary["realized_points"]),
        color="#ff7f0e",
        linewidth=2,
        linestyle="--",
        label=f"Manu realized={float(manu_summary['realized_points']):.0f}",
    )
    ax.axvline(
        float(nathan_summary["realized_points"]),
        color="#9467bd",
        linewidth=2,
        linestyle="--",
        label=f"Nathan realized={float(nathan_summary['realized_points']):.0f}",
    )
    ax.set_title("Transcribed Pronos vs Bookmaker-Injected Strategy")
    ax.set_xlabel("Total points")
    ax.set_ylabel("Density")
    ax.grid(color="#dddddd", linewidth=0.8)
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=180)
    plt.close(fig)


def main() -> None:
    manu_rows = read_csv(DEFAULT_MANU_FILE)
    nathan_rows = read_csv(DEFAULT_NATHAN_FILE)
    completed_rows = read_csv(DEFAULT_COMPLETED_FILE)
    odds_rows = read_csv(DEFAULT_ODDS_LOG)
    prediction_rows = read_csv(DEFAULT_PREDICTION_LOG)
    mpg_rows = read_csv(DEFAULT_MPG_FILE)

    manu_picks = build_manu_picks(manu_rows, completed_rows, odds_rows, prediction_rows)
    nathan_picks = build_transcribed_picks(
        nathan_rows,
        "nathan_prediction",
        completed_rows,
        odds_rows,
        prediction_rows,
    )
    bookmaker_picks = build_bookmaker_picks_from_odds(
        manu_picks,
        completed_rows,
        odds_rows,
        prediction_rows,
        mpg_rows,
    )
    random_games = build_random_player_games_from_odds(
        manu_picks,
        completed_rows,
        odds_rows,
        prediction_rows,
        mpg_rows,
    )

    manu_totals = simulation.simulate_totals(
        manu_picks,
        DEFAULT_ROLLOUTS,
        DEFAULT_SEED,
    )
    nathan_totals = simulation.simulate_totals(
        nathan_picks,
        DEFAULT_ROLLOUTS,
        DEFAULT_SEED + 3,
    )
    bookmaker_totals = simulation.simulate_totals(
        bookmaker_picks,
        DEFAULT_ROLLOUTS,
        DEFAULT_SEED + 1,
    )
    random_totals = simulation.simulate_random_player_totals(
        random_games,
        DEFAULT_ROLLOUTS,
        DEFAULT_SEED + 2,
    )
    manu_summary = summarize("manu_pronos", manu_picks, manu_totals)
    nathan_summary = summarize("nathan_pronos", nathan_picks, nathan_totals)
    bookmaker_summary = summarize("bookmaker_injected_top1", bookmaker_picks, bookmaker_totals)
    random_summary = summarize_random_player(random_games, random_totals)

    DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(
        DEFAULT_OUT_DIR / "manu_vs_bookmaker_summary.csv",
        [manu_summary, nathan_summary, bookmaker_summary, random_summary],
        SUMMARY_FIELDS,
    )
    write_csv(
        DEFAULT_OUT_DIR / "manu_scored_picks.csv",
        result_rows(manu_picks, "manu_pronos"),
        [*simulation.RESULT_FIELDS, "source"],
    )
    write_csv(
        DEFAULT_OUT_DIR / "bookmaker_scored_picks.csv",
        result_rows(bookmaker_picks, "bookmaker_injected_top1"),
        [*simulation.RESULT_FIELDS, "source"],
    )
    write_csv(
        DEFAULT_OUT_DIR / "nathan_scored_picks.csv",
        result_rows(nathan_picks, "nathan_pronos"),
        [*simulation.RESULT_FIELDS, "source"],
    )
    write_plot(
        DEFAULT_OUT_DIR / "manu_vs_bookmaker_distribution.png",
        manu_totals,
        manu_summary,
        nathan_totals,
        nathan_summary,
        bookmaker_totals,
        bookmaker_summary,
        random_totals,
        random_summary,
    )

    for summary in [manu_summary, nathan_summary, bookmaker_summary, random_summary]:
        print(
            f"{summary['strategy']}: games={summary['games']}, "
            f"realized={float(summary['realized_points']):.1f}, "
            f"mean={float(summary['simulation_mean']):.1f}, "
            f"percentile={100 * float(summary['realized_percentile']):.1f}%"
        )
    print(f"Saved outputs under: {DEFAULT_OUT_DIR}")


if __name__ == "__main__":
    main()
