#!/usr/bin/env python3
"""
Fetch FIFA World Cup 2026 first-round / group-stage odds from The Odds API
and write them to CSV.

Default behavior is deliberately cheap:
- 1 region: eu
- 3 markets: h2h, spreads, totals
- 1 odds request, after a sport-key discovery request
- all returned events are saved by default

Install:
  pip install requests

Run:
  python fetch_odds.py

Output:
  data/odds_snapshots/YYYY/MM/world_cup_first_round_odds_YYYYMMDDTHHMMSSZ.csv
  data/odds_snapshots/latest.csv
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

import odds_filters

# User explicitly requested the key be embedded directly in the code.
API_KEY = "[REMOVED_ODDS_API_KEY]"

BASE_URL = "https://api.the-odds-api.com/v4"

# FIFA World Cup 2026 group stage / first round.
# Starts 2026-06-11 and ends 2026-06-27; the upper bound below includes the full final day.
DEFAULT_FROM_TIME = "2026-06-10T00:00:00Z"
DEFAULT_TO_TIME = "2026-06-30T00:00:00Z"

DEFAULT_SNAPSHOT_DIR = "data/odds_snapshots"
DEFAULT_BASE_NAME = "world_cup_first_round_odds"
DEFAULT_REGION = "eu"
DEFAULT_MARKET = "h2h,spreads,totals"
DEFAULT_ODDS_FORMAT = "decimal"
DEFAULT_EVENT_OFFSET = 0
DEFAULT_EVENT_LIMIT = 0

CSV_FIELDS = [
    "event_id",
    "commence_time",
    "home_team",
    "away_team",
    "bookmaker_key",
    "bookmaker",
    "bookmaker_last_update",
    "market",
    "market_last_update",
    "outcome",
    "price",
    "point",
]


@dataclass
class ApiResult:
    data: Any
    response: requests.Response


def get_json(path: str, params: dict[str, Any]) -> ApiResult:
    params = dict(params)
    params["apiKey"] = API_KEY

    try:
        response = requests.get(f"{BASE_URL}{path}", params=params, timeout=30)
    except requests.RequestException as exc:
        safe_error = str(exc).replace(API_KEY, "[REDACTED_API_KEY]")
        raise SystemExit(f"Network/API request failed before receiving a response: {safe_error}") from exc

    if response.status_code != 200:
        # Avoid printing the URL because it contains the API key.
        raise SystemExit(
            f"The Odds API returned HTTP {response.status_code}.\n"
            f"Response body:\n{response.text}"
        )

    return ApiResult(data=response.json(), response=response)


def discover_world_cup_sport_key(preferred: str | None = None) -> str:
    """Find a match-odds World Cup sport key if the default is unavailable."""
    if preferred:
        return preferred

    # Common key used by The Odds API when World Cup match odds are available.
    default_guess = "soccer_fifa_world_cup"

    sports = get_json("/sports/", {"all": "true"}).data

    keys = {sport.get("key") for sport in sports}
    if default_guess in keys:
        return default_guess

    candidates: list[dict[str, Any]] = []
    for sport in sports:
        haystack = " ".join(
            str(sport.get(field, "")).lower()
            for field in ["key", "group", "title", "description"]
        )
        if "soccer" in haystack and "world cup" in haystack:
            candidates.append(sport)

    # Prefer match odds over outright/winner markets.
    non_outrights = [
        sport
        for sport in candidates
        if not sport.get("has_outrights")
        and "winner" not in str(sport.get("key", "")).lower()
        and "outright" not in str(sport.get("key", "")).lower()
    ]
    if non_outrights:
        return non_outrights[0]["key"]

    if candidates:
        print("World Cup-like sport keys found, but none looked like match odds:", file=sys.stderr)
        for sport in candidates:
            print(
                f"  {sport.get('key')} | {sport.get('title')} | "
                f"active={sport.get('active')} | has_outrights={sport.get('has_outrights')}",
                file=sys.stderr,
            )
        print("Pass the correct key manually with --sport-key.", file=sys.stderr)
        raise SystemExit(2)

    print("No World Cup sport key found right now.", file=sys.stderr)
    print("Available soccer keys:", file=sys.stderr)
    for sport in sports:
        key = str(sport.get("key", ""))
        group = str(sport.get("group", ""))
        if key.startswith("soccer_") or group.lower() == "soccer":
            print(
                f"  {sport.get('key')} | {sport.get('title')} | "
                f"active={sport.get('active')} | has_outrights={sport.get('has_outrights')}",
                file=sys.stderr,
            )
    raise SystemExit(2)


def fetch_odds(
    sport_key: str,
    regions: str,
    markets: str,
    odds_format: str,
    from_time: str,
    to_time: str,
) -> ApiResult:
    return get_json(
        f"/sports/{sport_key}/odds/",
        {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
            "dateFormat": "iso",
            "commenceTimeFrom": from_time,
            "commenceTimeTo": to_time,
        },
    )


def flatten_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for event in events:
        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if odds_filters.is_lay_market(str(market.get("key", ""))):
                    continue
                for outcome in market.get("outcomes", []):
                    rows.append(
                        {
                            "event_id": event.get("id"),
                            "commence_time": event.get("commence_time"),
                            "home_team": event.get("home_team"),
                            "away_team": event.get("away_team"),
                            "bookmaker_key": bookmaker.get("key"),
                            "bookmaker": bookmaker.get("title"),
                            "bookmaker_last_update": bookmaker.get("last_update"),
                            "market": market.get("key"),
                            "market_last_update": market.get("last_update"),
                            "outcome": outcome.get("name"),
                            "price": outcome.get("price"),
                            "point": outcome.get("point"),
                        }
                    )

    return rows


def select_event_window(
    events: list[dict[str, Any]],
    *,
    offset: int,
    limit: int | None,
) -> list[dict[str, Any]]:
    sorted_events = sorted(
        events,
        key=lambda event: (
            str(event.get("commence_time") or ""),
            str(event.get("id") or ""),
        ),
    )

    if limit is None:
        return sorted_events[offset:]

    return sorted_events[offset : offset + limit]


def snapshot_paths(snapshot_dir: str, base_name: str, now: datetime | None = None) -> tuple[Path, Path]:
    now = now or datetime.now(UTC)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    root = Path(snapshot_dir)
    dated_dir = root / now.strftime("%Y") / now.strftime("%m")
    snapshot_file = dated_dir / f"{base_name}_{timestamp}.csv"
    latest_file = root / "latest.csv"
    return snapshot_file, latest_file


def write_csv(
    rows: list[dict[str, Any]],
    out_file: str | Path,
    *,
    overwrite: bool = True,
) -> None:
    out_path = Path(out_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with open(out_path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def print_credit_headers(response: requests.Response) -> None:
    remaining = response.headers.get("x-requests-remaining")
    used = response.headers.get("x-requests-used")
    last = response.headers.get("x-requests-last")

    if last is not None:
        print(f"Credits used by odds call: {last}")
    if used is not None:
        print(f"Credits used total: {used}")
    if remaining is not None:
        print(f"Credits remaining: {remaining}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport-key", default=None, help="Override sport key, e.g. soccer_fifa_world_cup")
    parser.add_argument("--regions", default=DEFAULT_REGION, help="Cheap default: eu. Examples: eu, uk, eu,uk")
    parser.add_argument("--markets", default=DEFAULT_MARKET, help="Default: h2h,spreads,totals")
    parser.add_argument("--odds-format", default=DEFAULT_ODDS_FORMAT, choices=["decimal", "american"])
    parser.add_argument("--from-time", default=DEFAULT_FROM_TIME)
    parser.add_argument("--to-time", default=DEFAULT_TO_TIME)
    parser.add_argument(
        "--event-offset",
        type=int,
        default=DEFAULT_EVENT_OFFSET,
        help="Number of kickoff-sorted events to skip. Default saves from the first returned event.",
    )
    parser.add_argument(
        "--event-limit",
        type=int,
        default=DEFAULT_EVENT_LIMIT,
        help=(
            "Number of kickoff-sorted events to save after --event-offset. "
            "Use 0 for all remaining events. Default saves all returned events."
        ),
    )
    parser.add_argument(
        "--snapshot-dir",
        default=DEFAULT_SNAPSHOT_DIR,
        help="Directory where timestamped odds snapshots are saved.",
    )
    parser.add_argument(
        "--base-name",
        default=DEFAULT_BASE_NAME,
        help="Base filename used for timestamped snapshot CSVs.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional extra CSV path to write for backward compatibility or ad-hoc exports.",
    )
    parser.add_argument(
        "--no-latest",
        action="store_true",
        help="Do not update snapshot-dir/latest.csv after writing the timestamped snapshot.",
    )
    parser.add_argument(
        "--skip-discovery",
        action="store_true",
        help="Skip /sports discovery and use soccer_fifa_world_cup directly. Lowest number of API calls.",
    )
    args = parser.parse_args()

    if args.event_offset < 0:
        raise SystemExit("--event-offset must be non-negative.")
    if args.event_limit < 0:
        raise SystemExit("--event-limit must be non-negative.")

    if args.skip_discovery and not args.sport_key:
        sport_key = "soccer_fifa_world_cup"
    else:
        sport_key = discover_world_cup_sport_key(args.sport_key)

    print(f"Using sport key: {sport_key}")
    print(f"Date window: {args.from_time} to {args.to_time}")
    print(f"Regions: {args.regions}; markets: {args.markets}; odds format: {args.odds_format}")

    result = fetch_odds(
        sport_key=sport_key,
        regions=args.regions,
        markets=args.markets,
        odds_format=args.odds_format,
        from_time=args.from_time,
        to_time=args.to_time,
    )

    events = result.data
    selected_events = select_event_window(
        events,
        offset=args.event_offset,
        limit=None if args.event_limit == 0 else args.event_limit,
    )
    rows = flatten_events(selected_events)
    snapshot_file, latest_file = snapshot_paths(args.snapshot_dir, args.base_name)
    try:
        write_csv(rows, snapshot_file, overwrite=False)
    except FileExistsError as exc:
        raise SystemExit(
            f"Refusing to overwrite immutable odds snapshot: {snapshot_file}"
        ) from exc

    if not args.no_latest:
        latest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(snapshot_file, latest_file)

    if args.out:
        write_csv(rows, args.out)

    print(f"Events returned: {len(events)}")
    event_limit_label = "all remaining" if args.event_limit == 0 else str(args.event_limit)
    print(
        f"Events selected: {len(selected_events)} "
        f"(offset {args.event_offset}, limit {event_limit_label})"
    )
    print(f"CSV rows written: {len(rows)}")
    print_credit_headers(result.response)
    print(f"Saved snapshot: {snapshot_file}")
    if not args.no_latest:
        print(f"Updated latest CSV: {latest_file}")
    if args.out:
        print(f"Saved extra CSV: {args.out}")

    if not events:
        print(
            "No events were returned. This can mean the World Cup match-odds market is not active yet, "
            "the sport key differs, or the selected date window has no listed odds.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
