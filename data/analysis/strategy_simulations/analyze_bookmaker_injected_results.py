#!/usr/bin/env python3
"""Score bookmaker-injected top-1 picks and estimate their luck percentile."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bookmaker_injected_strategy


DEFAULT_PREDICTION_FILE = "data/bookmaker_injected/expected_mpg_top5.csv"
DEFAULT_ODDS_LOG_FILE = "data/bookmaker_injected/bookmaker_score_odds.csv"
DEFAULT_COMPLETED_FILE = "data/mpg/completed_games.csv"
DEFAULT_MPG_FILE = "data/mpg/mpg.txt"
DEFAULT_OUT_DIR = "data/analysis/strategy_simulations/bookmaker_injected"
DEFAULT_ROLLOUTS = 200_000
DEFAULT_SEED = 20260615
ACTUAL_EXACT_BONUS_OVERRIDES = {
    ("Ghana", "Panama", "1-0"): 20.0,
    ("Panama", "England", "0-2"): 30.0,
    ("Uruguay", "Spain", "0-1"): 70.0,
}

RESULT_FIELDS = [
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
]


@dataclass(frozen=True)
class ScoredPick:
    match: str
    commence_time: str
    selected_score: str
    actual_score: str
    outcome_probability: float
    exact_score_probability: float
    conditional_bettor_share: float
    conditional_share_sigma: float
    base_points: float
    expected_points: float
    outcome_correct: bool
    exact_score_correct: bool
    exact_bonus_points: float
    realized_points: float
    payout_multiplier: float = 1.0


@dataclass(frozen=True)
class RandomScoreCandidate:
    match: str
    commence_time: str
    score: str
    outcome: str
    outcome_probability: float
    exact_score_probability: float
    selection_probability: float
    conditional_bettor_share: float
    conditional_share_sigma: float
    base_points: float
    expected_points: float
    actual_score: str
    outcome_correct: bool
    exact_score_correct: bool
    exact_bonus_points: float
    realized_points: float


@dataclass(frozen=True)
class RandomGame:
    match: str
    commence_time: str
    candidates: tuple[RandomScoreCandidate, ...]


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_csv(
    path: Path, rows: list[dict[str, object]], fieldnames: list[str]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def normalize_team(team: str) -> str:
    return bookmaker_injected_strategy.normalize_team(team)


def parse_utc(value: str) -> dt.datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def top_pick_candidates(
    rows: list[dict[str, str]],
) -> dict[tuple[str, str], list[dict[str, str]]]:
    top_picks: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        if row["rank"] != "1":
            continue
        match = row["match"]
        if " vs " not in match:
            raise ValueError(f"Cannot parse match label {match!r}")
        home_team, away_team = match.split(" vs ", maxsplit=1)
        key = (normalize_team(home_team), normalize_team(away_team))
        top_picks.setdefault(key, []).append(row)
    for candidates in top_picks.values():
        candidates.sort(key=lambda row: parse_utc(row["logged_at_utc"]))
    return top_picks


def prediction_candidates(
    rows: list[dict[str, str]],
) -> dict[tuple[str, str], list[dict[str, str]]]:
    predictions: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        match = row["match"]
        if " vs " not in match:
            raise ValueError(f"Cannot parse match label {match!r}")
        home_team, away_team = match.split(" vs ", maxsplit=1)
        key = (normalize_team(home_team), normalize_team(away_team))
        predictions.setdefault(key, []).append(row)
    for candidates in predictions.values():
        candidates.sort(
            key=lambda row: (
                parse_utc(row["logged_at_utc"]),
                int(row.get("rank", "0") or "0"),
            )
        )
    return predictions


def latest_valid_top_pick(
    candidates: list[dict[str, str]],
    commence_time: str,
    prediction_cutoff_utc: str | None = None,
    require_pre_kickoff: bool = False,
) -> dict[str, str] | None:
    cutoffs = []
    if require_pre_kickoff:
        cutoffs.append(parse_utc(commence_time))
    if prediction_cutoff_utc is not None:
        cutoffs.append(parse_utc(prediction_cutoff_utc))
    if not cutoffs:
        return candidates[-1] if candidates else None
    cutoff = min(cutoffs)
    valid = [
        row
        for row in candidates
        if parse_utc(row["logged_at_utc"]) < cutoff
    ]
    return valid[-1] if valid else None


def latest_valid_submission_id(
    candidates: list[dict[str, str]],
    commence_time: str,
    prediction_cutoff_utc: str | None = None,
    require_pre_kickoff: bool = False,
) -> str | None:
    latest = latest_valid_top_pick(
        [row for row in candidates if row.get("rank") == "1"],
        commence_time,
        prediction_cutoff_utc,
        require_pre_kickoff,
    )
    return latest["submission_id"] if latest is not None else None


def mpg_points_lookup(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, float]]:
    return {
        (normalize_team(row["home_team"]), normalize_team(row["away_team"])): {
            "home": float(row["home_odds"]),
            "draw": float(row["draw_odds"]),
            "away": float(row["away_odds"]),
        }
        for row in rows
    }


def actual_exact_bonus_points(
    key: tuple[str, str],
    actual_score: str,
    fallback_points: float,
) -> float:
    return ACTUAL_EXACT_BONUS_OVERRIDES.get((*key, actual_score), fallback_points)


def score_completed_picks(
    prediction_rows: list[dict[str, str]],
    completed_rows: list[dict[str, str]],
    mpg_rows: list[dict[str, str]],
    prediction_cutoff_utc: str | None = None,
    require_pre_kickoff: bool = False,
) -> list[ScoredPick]:
    top_picks = top_pick_candidates(prediction_rows)
    points = mpg_points_lookup(mpg_rows)
    scored: list[ScoredPick] = []

    for completed in sorted(completed_rows, key=lambda row: row["commence_time"]):
        key = (
            normalize_team(completed["home_team"]),
            normalize_team(completed["away_team"]),
        )
        candidates = top_picks.get(key, [])
        prediction = latest_valid_top_pick(
            candidates,
            completed["commence_time"],
            prediction_cutoff_utc,
            require_pre_kickoff,
        )
        if prediction is None:
            continue
        if key not in points:
            raise ValueError(f"No MPG points found for {completed['home_team']} vs {completed['away_team']}")

        selected_outcome = prediction["outcome"]
        actual_home = int(completed["home_score"])
        actual_away = int(completed["away_score"])
        actual_outcome = bookmaker_injected_strategy.score_outcome(
            actual_home, actual_away
        )
        actual_score = f"{actual_home}-{actual_away}"
        outcome_correct = selected_outcome == actual_outcome
        exact_score_correct = prediction["score"] == actual_score
        base_points = points[key][selected_outcome]
        exact_bonus_points = (
            actual_exact_bonus_points(
                key,
                actual_score,
                float(prediction["nominal_bonus_points"]),
            )
            if exact_score_correct
            else 0.0
        )
        realized_points = (
            base_points + exact_bonus_points if outcome_correct else 0.0
        )
        scored.append(
            ScoredPick(
                match=prediction["match"],
                commence_time=completed["commence_time"],
                selected_score=prediction["score"],
                actual_score=actual_score,
                outcome_probability=float(prediction["outcome_probability"]),
                exact_score_probability=float(prediction["exact_score_probability"]),
                conditional_bettor_share=float(
                    prediction["conditional_bettor_share"]
                ),
                conditional_share_sigma=float(
                    prediction["conditional_share_sigma"]
                ),
                base_points=base_points,
                expected_points=float(prediction["total_ev"]),
                outcome_correct=outcome_correct,
                exact_score_correct=exact_score_correct,
                exact_bonus_points=exact_bonus_points,
                realized_points=realized_points,
            )
        )
    return scored


def odds_rows_by_submission(
    rows: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["submission_id"], []).append(row)
    return grouped


def outcome_probabilities_by_submission(
    rows: list[dict[str, str]],
) -> dict[str, dict[str, float]]:
    grouped: dict[str, dict[str, float]] = {}
    for row in rows:
        submission = row["submission_id"]
        grouped.setdefault(submission, {})
        grouped[submission][row["outcome"]] = float(row["outcome_probability"])
    return grouped


def build_random_game(
    completed: dict[str, str],
    submission_rows: list[dict[str, str]],
    outcome_probabilities: dict[str, float],
    points: dict[str, float],
    sigma: float,
) -> RandomGame:
    exact_rows = [
        row for row in submission_rows if row["score"].strip().lower() != "other"
    ]
    if not exact_rows:
        raise ValueError(f"No exact-score rows found for {completed['home_team']} vs {completed['away_team']}")

    raw_probability_total = sum(
        1.0 / float(row["odds_decimal"]) for row in submission_rows
    )
    bettor_total = sum(float(row["bet_percentage"]) for row in exact_rows)
    if raw_probability_total <= 0 or bettor_total <= 0:
        raise ValueError(f"Invalid bookmaker rows for {completed['home_team']} vs {completed['away_team']}")

    bettor_outcome_totals = {"home": 0.0, "draw": 0.0, "away": 0.0}
    raw_outcome_probabilities = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for row in exact_rows:
        outcome = bookmaker_injected_strategy.score_outcome(
            int(row["home_goals"]), int(row["away_goals"])
        )
        bettor_outcome_totals[outcome] += float(row["bet_percentage"])
        raw_outcome_probabilities[outcome] += (
            1.0 / float(row["odds_decimal"])
        ) / raw_probability_total

    actual_home = int(completed["home_score"])
    actual_away = int(completed["away_score"])
    actual_outcome = bookmaker_injected_strategy.score_outcome(actual_home, actual_away)
    actual_score = f"{actual_home}-{actual_away}"
    match = f"{completed['home_team']} vs {completed['away_team']}"
    key = (
        normalize_team(completed["home_team"]),
        normalize_team(completed["away_team"]),
    )
    candidates: list[RandomScoreCandidate] = []
    for row in exact_rows:
        outcome = bookmaker_injected_strategy.score_outcome(
            int(row["home_goals"]), int(row["away_goals"])
        )
        score_probability = (1.0 / float(row["odds_decimal"])) / raw_probability_total
        selection_probability = float(row["bet_percentage"]) / bettor_total
        conditional_share = (
            float(row["bet_percentage"]) / bettor_outcome_totals[outcome]
            if bettor_outcome_totals[outcome] > 0
            else 0.0
        )
        bonus = bookmaker_injected_strategy.bonus_distribution(
            conditional_share,
            sigma,
        )
        outcome_probability = outcome_probabilities.get(
            outcome,
            raw_outcome_probabilities[outcome],
        )
        base_points = points[outcome]
        expected_points = (
            outcome_probability * base_points
            + score_probability * bonus.expected_points
        )
        outcome_correct = outcome == actual_outcome
        exact_score_correct = row["score"] == actual_score
        exact_bonus_points = (
            actual_exact_bonus_points(key, actual_score, bonus.nominal_points)
            if exact_score_correct
            else 0.0
        )
        realized_points = (
            base_points + exact_bonus_points if outcome_correct else 0.0
        )
        candidates.append(
            RandomScoreCandidate(
                match=match,
                commence_time=completed["commence_time"],
                score=row["score"],
                outcome=outcome,
                outcome_probability=outcome_probability,
                exact_score_probability=score_probability,
                selection_probability=selection_probability,
                conditional_bettor_share=conditional_share,
                conditional_share_sigma=sigma,
                base_points=base_points,
                expected_points=expected_points,
                actual_score=actual_score,
                outcome_correct=outcome_correct,
                exact_score_correct=exact_score_correct,
                exact_bonus_points=exact_bonus_points,
                realized_points=realized_points,
            )
        )

    return RandomGame(
        match=match,
        commence_time=completed["commence_time"],
        candidates=tuple(candidates),
    )


def score_random_player_games(
    prediction_rows: list[dict[str, str]],
    odds_rows: list[dict[str, str]],
    completed_rows: list[dict[str, str]],
    mpg_rows: list[dict[str, str]],
    prediction_cutoff_utc: str | None = None,
    require_pre_kickoff: bool = False,
) -> list[RandomGame]:
    predictions = prediction_candidates(prediction_rows)
    odds_by_submission = odds_rows_by_submission(odds_rows)
    probabilities_by_submission = outcome_probabilities_by_submission(prediction_rows)
    points = mpg_points_lookup(mpg_rows)
    games: list[RandomGame] = []

    for completed in sorted(completed_rows, key=lambda row: row["commence_time"]):
        key = (
            normalize_team(completed["home_team"]),
            normalize_team(completed["away_team"]),
        )
        submission_id = latest_valid_submission_id(
            predictions.get(key, []),
            completed["commence_time"],
            prediction_cutoff_utc,
            require_pre_kickoff,
        )
        if submission_id is None:
            continue
        if key not in points:
            raise ValueError(f"No MPG points found for {completed['home_team']} vs {completed['away_team']}")
        submission_rows = odds_by_submission.get(submission_id)
        if not submission_rows:
            raise ValueError(f"No bookmaker odds rows found for submission {submission_id}")
        submission_predictions = [
            row for row in predictions[key] if row["submission_id"] == submission_id
        ]
        sigma = float(
            submission_predictions[0].get("conditional_share_sigma", "0.01")
            if submission_predictions
            else "0.01"
        )
        games.append(
            build_random_game(
                completed,
                submission_rows,
                probabilities_by_submission.get(submission_id, {}),
                points[key],
                sigma,
            )
        )

    return games


def sample_bonus_points(
    pick: ScoredPick, count: int, rng: np.random.Generator
) -> np.ndarray:
    shares = rng.normal(
        pick.conditional_bettor_share, pick.conditional_share_sigma, size=count
    )
    return np.select(
        [shares > 0.30, shares >= 0.20, shares >= 0.05, shares >= 0.005],
        [20.0, 30.0, 50.0, 70.0],
        default=100.0,
    )


def simulate_totals(
    picks: list[ScoredPick], rollouts: int, seed: int
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    totals = np.zeros(rollouts)
    for pick in picks:
        draws = rng.random(rollouts)
        exact = draws < pick.exact_score_probability
        outcome_only = (
            (draws >= pick.exact_score_probability)
            & (draws < pick.outcome_probability)
        )
        totals[outcome_only] += pick.base_points * pick.payout_multiplier
        exact_count = int(exact.sum())
        if exact_count:
            totals[exact] += (
                pick.base_points + sample_bonus_points(pick, exact_count, rng)
            ) * pick.payout_multiplier
    return totals


def simulate_random_player_totals(
    games: list[RandomGame], rollouts: int, seed: int
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    totals = np.zeros(rollouts)
    for game in games:
        probabilities = np.array(
            [candidate.selection_probability for candidate in game.candidates]
        )
        probabilities = probabilities / probabilities.sum()
        selected = rng.choice(len(game.candidates), size=rollouts, p=probabilities)
        draws = rng.random(rollouts)
        for index, candidate in enumerate(game.candidates):
            selected_mask = selected == index
            selected_count = int(selected_mask.sum())
            if not selected_count:
                continue
            candidate_draws = draws[selected_mask]
            exact = candidate_draws < candidate.exact_score_probability
            outcome_only = (
                (candidate_draws >= candidate.exact_score_probability)
                & (candidate_draws < candidate.outcome_probability)
            )
            totals[selected_mask] += outcome_only * candidate.base_points
            exact_count = int(exact.sum())
            if exact_count:
                exact_bonus = sample_bonus_points(
                    ScoredPick(
                        match=candidate.match,
                        commence_time=candidate.commence_time,
                        selected_score=candidate.score,
                        actual_score=candidate.actual_score,
                        outcome_probability=candidate.outcome_probability,
                        exact_score_probability=candidate.exact_score_probability,
                        conditional_bettor_share=candidate.conditional_bettor_share,
                        conditional_share_sigma=candidate.conditional_share_sigma,
                        base_points=candidate.base_points,
                        expected_points=candidate.expected_points,
                        outcome_correct=candidate.outcome_correct,
                        exact_score_correct=candidate.exact_score_correct,
                        exact_bonus_points=candidate.exact_bonus_points,
                        realized_points=candidate.realized_points,
                    ),
                    exact_count,
                    rng,
                )
                selected_indices = np.flatnonzero(selected_mask)
                totals[selected_indices[exact]] += candidate.base_points + exact_bonus
    return totals


def simulate_random_player_resolved_totals(
    games: list[RandomGame], players: int, seed: int
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    totals = np.zeros(players)
    for game in games:
        probabilities = np.array(
            [candidate.selection_probability for candidate in game.candidates]
        )
        probabilities = probabilities / probabilities.sum()
        realized_points = np.array(
            [candidate.realized_points for candidate in game.candidates]
        )
        selected = rng.choice(len(game.candidates), size=players, p=probabilities)
        totals += realized_points[selected]
    return totals


def random_player_realized_points(games: list[RandomGame]) -> float:
    return sum(
        candidate.selection_probability * candidate.realized_points
        for game in games
        for candidate in game.candidates
    )


def random_player_expected_points(games: list[RandomGame]) -> float:
    return sum(
        candidate.selection_probability * candidate.expected_points
        for game in games
        for candidate in game.candidates
    )


def result_rows(picks: list[ScoredPick]) -> list[dict[str, object]]:
    return [
        {
            "commence_time": pick.commence_time,
            "match": pick.match,
            "selected_score": pick.selected_score,
            "actual_score": pick.actual_score,
            "outcome_correct": pick.outcome_correct,
            "exact_score_correct": pick.exact_score_correct,
            "base_points": pick.base_points if pick.outcome_correct else 0.0,
            "exact_bonus_points": pick.exact_bonus_points,
            "realized_points": pick.realized_points,
            "expected_points": pick.expected_points,
            "realized_minus_expected": pick.realized_points
            - pick.expected_points,
        }
        for pick in picks
    ]


def write_plot(
    path: Path,
    totals: np.ndarray,
    realized: float,
    title: str = "Bookmaker-injected top-1 strategy: resolved points vs simulated EV range",
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpp-matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mean = float(totals.mean())
    sigma = float(totals.std())
    percentile = float(np.mean(totals <= realized))

    fig, (box_ax, hist_ax) = plt.subplots(
        2, 1, figsize=(11, 7), gridspec_kw={"height_ratios": [1, 3]}
    )
    box_ax.boxplot(
        totals,
        vert=False,
        widths=0.5,
        showfliers=False,
        patch_artist=True,
        boxprops={"facecolor": "#9ecae1", "edgecolor": "#174a7e"},
        medianprops={"color": "#174a7e", "linewidth": 2},
    )
    box_ax.scatter(
        [realized], [1], marker="D", s=80, color="#c62828", zorder=5,
        label=f"Resolved: {realized:.0f}",
    )
    box_ax.axvline(mean, color="#e66101", linewidth=2, label=f"Mean EV: {mean:.1f}")
    box_ax.set_yticks([])
    box_ax.set_title(title)
    box_ax.legend(loc="upper left", ncol=2)

    hist_ax.hist(totals, bins=70, density=True, color="#9ecae1", edgecolor="white")
    colors = {"1": "#e6ab02", "2": "#7570b3"}
    for multiple in (1, 2):
        low = mean - multiple * sigma
        high = mean + multiple * sigma
        hist_ax.axvline(
            low, color=colors[str(multiple)], linestyle="--", linewidth=1.5
        )
        hist_ax.axvline(
            high,
            color=colors[str(multiple)],
            linestyle="--",
            linewidth=1.5,
            label=f"Mean ± {multiple}σ: {low:.0f} to {high:.0f}",
        )
    hist_ax.axvline(mean, color="#e66101", linewidth=2)
    hist_ax.axvline(realized, color="#c62828", linewidth=2.5)
    hist_ax.annotate(
        f"Resolved {realized:.0f}\n{percentile:.1%} percentile",
        xy=(realized, hist_ax.get_ylim()[1] * 0.72),
        xytext=(12, 0),
        textcoords="offset points",
        color="#c62828",
        fontweight="bold",
    )
    hist_ax.set_xlabel("Total points over completed games")
    hist_ax.set_ylabel("Simulated density")
    hist_ax.grid(axis="y", color="#e0e0e0", linewidth=0.8)
    hist_ax.legend(loc="upper right")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_comparison_plot(
    path: Path,
    bookmaker_totals: np.ndarray,
    bookmaker_realized: float,
    random_totals: np.ndarray,
    random_realized: float,
    difference_totals: np.ndarray | None = None,
    difference_realized: float | None = None,
    random_resolved_totals: np.ndarray | None = None,
    title: str = "Bookmaker-injected top-1 vs random MPG player",
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpp-matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if difference_totals is None:
        difference_totals = bookmaker_totals - random_totals
    if difference_realized is None:
        difference_realized = bookmaker_realized - random_realized

    fig, (bookmaker_ax, random_ax, difference_ax) = plt.subplots(
        3,
        1,
        figsize=(12, 10),
        gridspec_kw={"height_ratios": [1, 1, 1]},
    )

    strategy_series = [
        (
            bookmaker_ax,
            "Bookmaker-injected top-1 strategy",
            bookmaker_totals,
            bookmaker_realized,
            "#1f77b4",
        ),
        (
            random_ax,
            "Random MPG player: exact scores sampled by bettor share",
            random_totals,
            random_realized,
            "#ff7f0e",
        ),
    ]
    for axis, label, totals, realized, color in strategy_series:
        mean = float(np.mean(totals))
        percentile = float(np.mean(totals <= realized))
        axis.hist(
            totals,
            bins=70,
            density=True,
            alpha=0.58,
            color=color,
            edgecolor="white",
            linewidth=0.25,
            label=f"{label} distribution ({percentile:.1%} resolved percentile)",
        )
        y_top = axis.get_ylim()[1]
        axis.axvline(
            mean,
            color=color,
            linewidth=1.8,
            linestyle="--",
            label="Simulated mean",
        )
        axis.axvline(
            realized,
            color=color,
            linewidth=2.4,
            label="Resolved result",
        )
        axis.annotate(
            f"{mean:.1f}",
            xy=(mean, y_top * 0.80),
            xytext=(5, 0),
            textcoords="offset points",
            color=color,
            fontsize=8,
            fontweight="bold",
        )
        axis.annotate(
            f"{realized:.1f}",
            xy=(realized, y_top * 0.66),
            xytext=(5, 0),
            textcoords="offset points",
            color=color,
            fontsize=8,
            fontweight="bold",
        )
        axis.set_ylabel("Simulated density")
        axis.grid(axis="y", color="#e0e0e0", linewidth=0.8)
        axis.legend(loc="upper left", fontsize=8)

    shared_low = min(float(np.min(bookmaker_totals)), float(np.min(random_totals)))
    shared_high = max(float(np.max(bookmaker_totals)), float(np.max(random_totals)))
    shared_padding = (shared_high - shared_low) * 0.04
    bookmaker_ax.set_xlim(shared_low - shared_padding, shared_high + shared_padding)
    random_ax.set_xlim(shared_low - shared_padding, shared_high + shared_padding)
    bookmaker_ax.set_title(title)
    random_ax.set_title("Random-player total-point distribution")
    random_ax.set_xlabel("Total points over completed games")

    difference_mean = float(np.mean(difference_totals))
    difference_percentile = float(np.mean(difference_totals <= difference_realized))
    random_more_theory_share = float(np.mean(difference_totals < 0))
    random_more_resolved_share = (
        float(np.mean(random_resolved_totals > bookmaker_realized))
        if random_resolved_totals is not None
        else None
    )
    difference_ax.hist(
        difference_totals,
        bins=70,
        density=True,
        alpha=0.58,
        color="#2ca02c",
        edgecolor="white",
        linewidth=0.25,
        label=f"Difference distribution ({difference_percentile:.1%} resolved percentile)",
    )
    difference_y_top = difference_ax.get_ylim()[1]
    difference_ax.axvline(
        0,
        color="#555555",
        linewidth=1.2,
        alpha=0.7,
        label="Break-even",
    )
    difference_ax.axvline(
        difference_mean,
        color="#2ca02c",
        linewidth=1.8,
        linestyle="--",
        label="Simulated mean",
    )
    difference_ax.axvline(
        difference_realized,
        color="#2ca02c",
        linewidth=2.4,
        label="Resolved result",
    )
    difference_ax.annotate(
        (
            "0: random higher\n"
            f"Theory: {random_more_theory_share:.1%}"
            + (
                f"\nResolved: {random_more_resolved_share:.1%}"
                if random_more_resolved_share is not None
                else ""
            )
        ),
        xy=(0, difference_y_top * 0.92),
        xytext=(7, -2),
        textcoords="offset points",
        color="#555555",
        fontsize=8,
        fontweight="bold",
        bbox={
            "boxstyle": "round,pad=0.25",
            "facecolor": "white",
            "edgecolor": "#cccccc",
            "alpha": 0.85,
        },
    )
    difference_ax.annotate(
        f"{difference_mean:+.1f}",
        xy=(difference_mean, difference_y_top * 0.78),
        xytext=(5, 0),
        textcoords="offset points",
        color="#2ca02c",
        fontsize=8,
        fontweight="bold",
    )
    difference_ax.annotate(
        f"{difference_realized:+.1f}",
        xy=(difference_realized, difference_y_top * 0.64),
        xytext=(5, 0),
        textcoords="offset points",
        color="#2ca02c",
        fontsize=8,
        fontweight="bold",
    )

    difference_ax.set_title("Difference distribution")
    difference_ax.set_xlabel("Bookmaker-injected points minus random-player points")
    difference_ax.set_ylabel("Simulated density")
    difference_ax.grid(axis="y", color="#e0e0e0", linewidth=0.8)
    difference_ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_resolved_random_player_plot(
    path: Path,
    random_totals: np.ndarray,
    bookmaker_realized: float,
    title: str = "Resolved random-player scores vs bookmaker-injected top-1",
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpp-matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mean = float(np.mean(random_totals))
    sigma = float(np.std(random_totals))
    percentile = float(np.mean(random_totals <= bookmaker_realized))

    fig, ax = plt.subplots(figsize=(12, 6))
    densities, bin_edges, _ = ax.hist(
        random_totals,
        bins=70,
        density=True,
        alpha=0.58,
        color="#ff7f0e",
        edgecolor="white",
        linewidth=0.25,
        label=f"Random players ({percentile:.1%} scored <= bookmaker)",
    )
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    bookmaker_density = float(np.interp(bookmaker_realized, bin_centers, densities))
    ax.plot(
        bin_centers,
        densities,
        color="#ff7f0e",
        linewidth=1.8,
    )
    y_top = ax.get_ylim()[1]
    ax.axvline(
        mean,
        color="#ff7f0e",
        linewidth=1.8,
        linestyle="--",
        label="Random-player mean",
    )
    ax.axvline(
        bookmaker_realized,
        color="#1f77b4",
        linewidth=2.5,
        label="Bookmaker top-1",
    )
    ax.scatter(
        [bookmaker_realized],
        [bookmaker_density],
        marker="D",
        s=64,
        color="#1f77b4",
        edgecolor="white",
        linewidth=0.8,
        zorder=5,
    )
    ax.annotate(
        f"{mean:.1f}",
        xy=(mean, y_top * 0.82),
        xytext=(5, 0),
        textcoords="offset points",
        color="#ff7f0e",
        fontsize=9,
        fontweight="bold",
    )
    ax.annotate(
        f"{bookmaker_realized:.1f}",
        xy=(bookmaker_realized, bookmaker_density),
        xytext=(8, 8),
        textcoords="offset points",
        color="#1f77b4",
        fontsize=9,
        fontweight="bold",
    )
    ax.set_title(title)
    ax.set_xlabel("Total realized points over completed games")
    ax.set_ylabel("Player density")
    ax.grid(axis="y", color="#e0e0e0", linewidth=0.8)
    ax.legend(loc="upper left", fontsize=9)
    ax.text(
        0.99,
        0.95,
        f"Random mean / sd: {mean:.1f} / {sigma:.1f}",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=9,
    )
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prediction-file", default=DEFAULT_PREDICTION_FILE)
    parser.add_argument("--odds-log-file", default=DEFAULT_ODDS_LOG_FILE)
    parser.add_argument("--completed-file", default=DEFAULT_COMPLETED_FILE)
    parser.add_argument("--mpg-file", default=DEFAULT_MPG_FILE)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--rollouts", type=int, default=DEFAULT_ROLLOUTS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--prediction-cutoff-utc",
        help="Only include rank-1 predictions logged before this UTC timestamp.",
    )
    parser.add_argument(
        "--require-pre-kickoff",
        action="store_true",
        help="Only include rank-1 predictions logged before each match kickoff.",
    )
    parser.add_argument("--write-rollouts", action="store_true")
    parser.add_argument("--write-plot", action="store_true")
    parser.add_argument(
        "--include-random-player",
        action="store_true",
        help=(
            "Also simulate a random MPG player who samples exact-score picks "
            "proportionally to displayed bettor shares."
        ),
    )
    args = parser.parse_args()
    if args.rollouts <= 0:
        raise SystemExit("--rollouts must be positive")

    prediction_rows = read_csv(args.prediction_file)
    completed_rows = read_csv(args.completed_file)
    mpg_rows = read_csv(args.mpg_file)
    picks = score_completed_picks(
        prediction_rows,
        completed_rows,
        mpg_rows,
        args.prediction_cutoff_utc,
        args.require_pre_kickoff,
    )
    if not picks:
        raise SystemExit("No completed games matched bookmaker-injected top-1 picks")

    totals = simulate_totals(picks, args.rollouts, args.seed)
    realized = sum(pick.realized_points for pick in picks)
    expected = sum(pick.expected_points for pick in picks)
    mean = float(totals.mean())
    sigma = float(totals.std())
    percentile = float(np.mean(totals <= realized))

    out_dir = Path(args.out_dir)
    results_path = out_dir / "completed_top1_results.csv"
    write_csv(results_path, result_rows(picks), RESULT_FIELDS)
    if args.write_rollouts:
        rollouts_path = out_dir / "top1_total_rollouts.csv"
        write_csv(
            rollouts_path,
            [
                {"rollout": index + 1, "total_points": float(total)}
                for index, total in enumerate(totals)
            ],
            ["rollout", "total_points"],
        )
        print(f"Saved rollouts: {rollouts_path}")
    if args.write_plot:
        plot_path = out_dir / "top1_luck_distribution.png"
        write_plot(plot_path, totals, realized)
        print(f"Saved plot: {plot_path}")

    random_summary = None
    if args.include_random_player:
        random_games = score_random_player_games(
            prediction_rows,
            read_csv(args.odds_log_file),
            completed_rows,
            mpg_rows,
            args.prediction_cutoff_utc,
            args.require_pre_kickoff,
        )
        if not random_games:
            raise SystemExit("No completed games matched random-player bookmaker rows")
        random_totals = simulate_random_player_totals(
            random_games,
            args.rollouts,
            args.seed + 1,
        )
        random_resolved_totals = simulate_random_player_resolved_totals(
            random_games,
            args.rollouts,
            args.seed + 2,
        )
        random_realized = random_player_realized_points(random_games)
        random_expected = random_player_expected_points(random_games)
        difference_totals = totals - random_totals
        difference_realized = realized - random_realized
        random_summary = {
            "games": len(random_games),
            "realized": random_realized,
            "expected": random_expected,
            "mean": float(np.mean(random_totals)),
            "sigma": float(np.std(random_totals)),
            "percentile": float(np.mean(random_totals <= random_realized)),
            "difference_realized": difference_realized,
            "difference_mean": float(np.mean(difference_totals)),
            "difference_sigma": float(np.std(difference_totals)),
            "difference_percentile": float(
                np.mean(difference_totals <= difference_realized)
            ),
            "resolved_sample_mean": float(np.mean(random_resolved_totals)),
            "resolved_sample_sigma": float(np.std(random_resolved_totals)),
            "bookmaker_vs_resolved_sample_percentile": float(
                np.mean(random_resolved_totals <= realized)
            ),
        }
        if args.write_plot:
            comparison_plot = out_dir / "top1_vs_random_player_distribution.png"
            write_comparison_plot(
                comparison_plot,
                totals,
                realized,
                random_totals,
                random_realized,
                difference_totals,
                difference_realized,
                random_resolved_totals,
            )
            print(f"Saved comparison plot: {comparison_plot}")
            resolved_plot = out_dir / "random_player_resolved_points_distribution.png"
            write_resolved_random_player_plot(
                resolved_plot,
                random_resolved_totals,
                realized,
            )
            print(f"Saved resolved random-player plot: {resolved_plot}")

    print(f"Completed bookmaker top-1 picks: {len(picks)}")
    print(f"Realized points: {realized:.2f}")
    print(f"Logged expected points: {expected:.2f}")
    print(f"Realized minus EV: {realized - expected:+.2f}")
    print(f"Simulated mean / standard deviation: {mean:.2f} / {sigma:.2f}")
    print(f"Realized percentile (lower means unluckier): {percentile:.2%}")
    print(f"Mean ± 1σ: {mean - sigma:.2f} to {mean + sigma:.2f}")
    print(f"Mean ± 2σ: {mean - 2 * sigma:.2f} to {mean + 2 * sigma:.2f}")
    print(f"Saved per-game results: {results_path}")
    if random_summary is not None:
        print("")
        print(f"Completed random MPG player games: {random_summary['games']}")
        print(f"Random realized expected points: {random_summary['realized']:.2f}")
        print(f"Random expected points: {random_summary['expected']:.2f}")
        print(
            "Random simulated mean / standard deviation: "
            f"{random_summary['mean']:.2f} / {random_summary['sigma']:.2f}"
        )
        print(f"Random realized percentile: {random_summary['percentile']:.2%}")
        print("")
        print("Difference: bookmaker top-1 minus random MPG player")
        print(
            f"Realized difference: {random_summary['difference_realized']:+.2f}"
        )
        print(
            f"Expected mean difference: {random_summary['difference_mean']:+.2f}"
        )
        print(
            "Difference simulated mean / standard deviation: "
            f"{random_summary['difference_mean']:.2f} / "
            f"{random_summary['difference_sigma']:.2f}"
        )
        print(
            "Realized difference percentile: "
            f"{random_summary['difference_percentile']:.2%}"
        )
        print("")
        print("Resolved games: sampled random players by bettor share")
        print(
            "Random-player realized mean / standard deviation: "
            f"{random_summary['resolved_sample_mean']:.2f} / "
            f"{random_summary['resolved_sample_sigma']:.2f}"
        )
        print(
            "Bookmaker-injected top-1 percentile vs random players: "
            f"{random_summary['bookmaker_vs_resolved_sample_percentile']:.2%}"
        )


if __name__ == "__main__":
    main()
