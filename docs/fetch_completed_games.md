# Fetching Completed Games

Completed FIFA World Cup results come from The Odds API scores endpoint:

```text
GET https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/scores/
```

This is separate from the odds endpoint used by `fetch_odds.py`.

## Request

Query parameters:

| Parameter | Value | Meaning |
|---|---|---|
| `apiKey` | The Odds API key | Authentication. |
| `daysFrom` | Usually `3` | Include games commencing within this many days in the past. |
| `dateFormat` | `iso` | Return ISO-8601 UTC timestamps. |

Repository command:

```bash
.venv/bin/python -c "
import json
import fetch_odds

result = fetch_odds.get_json(
    '/sports/soccer_fifa_world_cup/scores/',
    {'daysFrom': 3, 'dateFormat': 'iso'},
)
print(json.dumps(result.data, indent=2))
fetch_odds.print_credit_headers(result.response)
"
```

The request needs network access. `fetch_odds.get_json` adds the embedded API
key and redacts it from connection errors.

The scores request used 2 API credits on June 12, 2026. Always inspect the
`x-requests-last`, `x-requests-used`, and `x-requests-remaining` response
headers because API pricing can change.

## Response Shape

Each returned event has this structure:

```json
{
  "id": "d1f4f946c70a0b4e81f5d43e9d32361c",
  "commence_time": "2026-06-12T19:02:00Z",
  "completed": true,
  "home_team": "Canada",
  "away_team": "Bosnia & Herzegovina",
  "scores": [
    {"name": "Canada", "score": "1"},
    {"name": "Bosnia & Herzegovina", "score": "1"}
  ],
  "last_update": "2026-06-12T22:55:23Z"
}
```

Only import an event when:

```text
completed == true
scores is not null
```

Do not infer a final result from `commence_time`, or import live scores from an
event where `completed` is false.

The score array is keyed by team name. Do not assume array position alone:

```text
home_score = score whose name equals home_team
away_score = score whose name equals away_team
```

Scores are returned as strings and must be converted to integers.

## Output File

Merge completed events into:

```text
data/mpg/completed_games.csv
```

The API `id` is the stable merge key. Re-fetching results must update an
existing row with the same `event_id`, not append a duplicate. Preserve rows
for completed games that are outside the current API response window.

Keep rows in match schedule order.

Columns:

| Column | Source or calculation |
|---|---|
| `event_id` | API `id`. |
| `commence_time` | API `commence_time`. |
| `home_team` | API `home_team`. |
| `away_team` | API `away_team`. |
| `home_score` | Score matched to `home_team`. |
| `away_score` | Score matched to `away_team`. |
| `final_score` | `home_score-away_score`. |
| `optimal_pick` | `optimal_pick` from `data/mpg/mpg_optimal_strategy.csv`. |
| `optimal_exact_score` | `optimal_exact_score` from the same strategy row. |
| `outcome_correct` | Whether `optimal_pick` matches the realized outcome. |
| `exact_score_correct` | Whether `optimal_exact_score` equals `final_score`. |
| `base_points` | Selected outcome's MPG payout when `outcome_correct`; otherwise `0`. |
| `actual_exact_bonus_points` | `exact_bonus_points` for the realized score from `data/mpg/mpg_score_expected_values.csv`. |
| `total_points` | `base_points` plus the bonus only when the exact score was selected correctly. |
| `api_last_update` | API `last_update`. |

`actual_exact_bonus_points` describes the realized score's tier for simulation
scoring. It is recorded even when the strategy predicted another score.
`total_points` receives that bonus only when `exact_score_correct` is true.
The scores API does not provide this MPG bonus.

Match the strategy and score-EV rows by normalized home and away team names.
Then select the score-EV row whose `score` equals `final_score`. For an
out-of-grid final score with no score-EV row, record an exact bonus of `0`.

Example: if the final is `1-1`, its tier is 20 points, but a strategy that
selected `Canada 2-1` earns zero:

```text
outcome_correct = False
exact_score_correct = False
base_points = 0
actual_exact_bonus_points = 20
total_points = 0
```

## Team Matching

Use `event_id` whenever possible. Team names can differ between MPG and API
data. Existing aliases include:

```text
Bosnia -> Bosnia & Herzegovina
Cote d'Ivoire -> Ivory Coast
Curacao -> Curaçao
Czechia -> Czech Republic
United States -> USA
```

Do not rewrite the API team names in `completed_games.csv`; the simulation
joins completed results to probabilities by `event_id`.

## Validation

After updating the file:

```bash
.venv/bin/python -m unittest tests.test_simulate_mpg_strategy
```

Run a small simulation outside the tracked analysis directory:

```bash
.venv/bin/python simulate_mpg_strategy.py \
  --rollouts 10 \
  --out-dir /tmp/mpp-results-validation
```

Confirm that `Completed games resolved from results` equals the number of
unique event IDs in `completed_games.csv`.
