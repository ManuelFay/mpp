"""Probability adjustments for knockout games scored before penalties."""

from __future__ import annotations

from datetime import datetime, timezone

GAME_STAGE_GROUP = "group"
GAME_STAGE_ELIMINATION = "elimination"
ROUND_OF_32_FROM = datetime(2026, 6, 28, tzinfo=timezone.utc)
ROUND_OF_32_TO = datetime(2026, 7, 5, tzinfo=timezone.utc)
DRAW_RETENTION_PROBABILITY_MULTIPLIER = 3.0
MAX_DRAW_RETENTION_FACTOR = 0.90


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def game_stage_for_commence_time(commence_time: str | None) -> str:
    if not commence_time:
        return GAME_STAGE_GROUP
    kickoff = parse_utc(commence_time)
    if ROUND_OF_32_FROM <= kickoff < ROUND_OF_32_TO:
        return GAME_STAGE_ELIMINATION
    return GAME_STAGE_GROUP


def is_elimination_stage(stage: str | None) -> bool:
    return (stage or GAME_STAGE_GROUP).strip().lower() == GAME_STAGE_ELIMINATION


def corrected_outcome_probabilities(
    home_probability: float,
    draw_probability: float,
    away_probability: float,
) -> tuple[dict[str, float], dict[str, float]]:
    draw_retention_factor = min(
        MAX_DRAW_RETENTION_FACTOR,
        draw_probability * DRAW_RETENTION_PROBABILITY_MULTIPLIER,
    )
    corrected_draw = draw_probability * draw_retention_factor
    released_draw = draw_probability - corrected_draw
    non_draw_total = home_probability + away_probability

    if non_draw_total > 0:
        home_share = home_probability / non_draw_total
        away_share = away_probability / non_draw_total
    else:
        home_share = away_share = 0.5
    corrected_home = home_probability + released_draw * home_share
    corrected_away = away_probability + released_draw * away_share

    return (
        {
            "home": corrected_home,
            "draw": corrected_draw,
            "away": corrected_away,
        },
        {
            "draw_retention_factor": draw_retention_factor,
            "home_share": home_share,
            "away_share": away_share,
        },
    )
