# Fetching Odds

Script:

```text
fetch_odds.py
```

Purpose:

- Calls The Odds API.
- Downloads World Cup 2026 group-stage odds.
- Flattens the nested API response into CSV rows.
- Stores every run as a timestamped snapshot.
- Updates `data/odds_snapshots/latest.csv`.

## Default Command

```bash
python3 fetch_odds.py --skip-discovery
```

`--skip-discovery` avoids an extra `/sports` API call and uses:

```text
soccer_fifa_world_cup
```

as the sport key.

## Default Date Window

The script is configured for the World Cup 2026 group stage:

```text
from: 2026-06-10T00:00:00Z
to:   2026-06-30T00:00:00Z
```

This intentionally covers the full first round/group stage window.

## Default Markets

The default market set is:

```text
h2h,spreads,totals
```

The Odds API may also return `h2h_lay` rows for exchanges such as Betfair or
Matchbook. The fetcher excludes all markets ending in `_lay` from saved
snapshots.

## Output Location

Each run writes:

```text
data/odds_snapshots/YYYY/MM/world_cup_first_round_odds_YYYYMMDDTHHMMSSZ.csv
```

and updates:

```text
data/odds_snapshots/latest.csv
```

The timestamp is UTC.

## CSV Columns

Raw snapshot columns:

| Column | Meaning |
|---|---|
| `event_id` | The Odds API event id. |
| `commence_time` | Match start time in ISO format. |
| `home_team` | Home team from the API. |
| `away_team` | Away team from the API. |
| `bookmaker_key` | Stable bookmaker key. |
| `bookmaker` | Human-readable bookmaker name. |
| `bookmaker_last_update` | Bookmaker update timestamp. |
| `market` | Market key, such as `h2h`, `totals`, or `spreads`. |
| `market_last_update` | Market update timestamp. |
| `outcome` | Outcome name, such as a team, `Draw`, `Over`, or `Under`. |
| `price` | Decimal odds. |
| `point` | Spread or total line, where applicable. |

## Useful Options

Use a different region:

```bash
python3 fetch_odds.py --skip-discovery --regions eu,uk
```

Fetch only `h2h`:

```bash
python3 fetch_odds.py --skip-discovery --markets h2h
```

Write an extra compatibility file:

```bash
python3 fetch_odds.py --skip-discovery --out world_cup_first_round_odds.csv
```

Use a different snapshot directory:

```bash
python3 fetch_odds.py --skip-discovery --snapshot-dir data/my_snapshots
```

Disable `latest.csv` update:

```bash
python3 fetch_odds.py --skip-discovery --no-latest
```

## API Credit Cost

The Odds API charges per market and per region. With one region and three markets:

```text
regions = eu
markets = h2h,spreads,totals
```

the odds call uses 3 credits. If sport-key discovery is enabled, the discovery call may also count depending on the API plan and endpoint behavior.

## Network Failures

If the script cannot resolve or reach `api.the-odds-api.com`, the request fails before producing a snapshot. The error redacts the API key.
