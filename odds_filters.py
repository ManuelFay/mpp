"""Shared validation rules for raw odds snapshot rows."""

from __future__ import annotations

from collections import defaultdict


MIN_H2H_IMPLIED_PROBABILITY = 0.85
MAX_H2H_IMPLIED_PROBABILITY = 1.20


def is_lay_market(market: str) -> bool:
    return market.endswith("_lay")


def valid_h2h_outcomes(outcomes: dict[str, float]) -> bool:
    implied_probability = sum(1 / price for price in outcomes.values())
    return MIN_H2H_IMPLIED_PROBABILITY <= implied_probability <= MAX_H2H_IMPLIED_PROBABILITY


def filter_snapshot_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Remove lay rows and invalid complete h2h bookmaker-event groups."""
    non_lay_rows = [row for row in rows if not is_lay_market(row.get("market", ""))]
    h2h_groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)

    for row in non_lay_rows:
        if row.get("market") == "h2h" and row.get("price"):
            h2h_groups[(row["event_id"], row["bookmaker_key"])].append(row)

    invalid_h2h_groups = set()
    for key, group_rows in h2h_groups.items():
        outcomes = {row["outcome"]: float(row["price"]) for row in group_rows}
        if len(outcomes) == len(group_rows) and not valid_h2h_outcomes(outcomes):
            invalid_h2h_groups.add(key)

    return [
        row
        for row in non_lay_rows
        if row.get("market") != "h2h" or (row["event_id"], row["bookmaker_key"]) not in invalid_h2h_groups
    ]
