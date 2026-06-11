# Processing Latest Odds

Script:

```text
process_latest_odds.py
```

Purpose:

- Reads `data/odds_snapshots/latest.csv`.
- Computes per-game `h2h` implied probabilities.
- Fits an exact-score model for each game.
- Writes processed CSV outputs.

## Default Command

```bash
python3 process_latest_odds.py
```

## Inputs

Default input:

```text
data/odds_snapshots/latest.csv
```

Override input:

```bash
python3 process_latest_odds.py --in-file path/to/snapshot.csv
```

## Outputs

Default game probability output:

```text
data/processed/latest_game_probabilities.csv
```

Default exact-score output:

```text
data/processed/latest_exact_score_probabilities.csv
```

Default calibrated exact-score output:

```text
data/processed/latest_exact_score_probabilities_calibrated.csv
```

Default score-shape multiplier output:

```text
data/processed/latest_score_shape_calibration_multipliers.csv
```

Override outputs:

```bash
python3 process_latest_odds.py \
  --out data/processed/game_probabilities_custom.csv \
  --exact-score-out data/processed/exact_scores_custom.csv \
  --calibrated-exact-score-out data/processed/exact_scores_calibrated_custom.csv
```

## Game Probability Output

`latest_game_probabilities.csv` has one row per game.

Columns:

| Column | Meaning |
|---|---|
| `event_id` | The Odds API event id. |
| `commence_time` | Match start time. |
| `home_team` | Home team. |
| `away_team` | Away team. |
| `market` | Usually `h2h`. |
| `bookmaker_count` | Number of complete 1X2 bookmaker markets used. |
| `home_probability` | Vig-removed average home win probability. |
| `draw_probability` | Vig-removed average draw probability. |
| `away_probability` | Vig-removed average away win probability. |
| `home_avg_odds` | Average raw decimal odds for home win. |
| `draw_avg_odds` | Average raw decimal odds for draw. |
| `away_avg_odds` | Average raw decimal odds for away win. |
| `favorite` | Outcome with highest probability. |
| `favorite_probability` | Probability of the favorite. |
| `favorite_gap_to_second` | Probability gap between favorite and second-most likely outcome. |

## H2H Probability Method

For each bookmaker with complete home/draw/away odds:

```text
implied_home = 1 / home_odds
implied_draw = 1 / draw_odds
implied_away = 1 / away_odds
overround = implied_home + implied_draw + implied_away
normalized_home = implied_home / overround
normalized_draw = implied_draw / overround
normalized_away = implied_away / overround
```

The script averages the normalized probabilities across bookmakers.

Incomplete bookmaker markets are skipped. For example, if a bookmaker is missing the draw price, that bookmaker is not used for that game.

Lay markets such as `h2h_lay` are excluded. Complete `h2h` bookmaker markets
are also skipped when their summed implied probability is outside `0.85` to
`1.20`, which catches malformed or illiquid exchange quotes before they affect
the averaged probabilities or exact-score model.

## Exact Score Output

`latest_exact_score_probabilities.csv` contains one row per game with:

- model parameters
- model-implied h2h probabilities
- 0-0 through 4-4 exact-score probabilities
- `other_probability`
- split of `other_probability` into home/draw/away portions

See [Exact Score Model](exact_score_model.md) for details.

## Calibrated Exact Score Output

`latest_exact_score_probabilities_calibrated.csv` has the same score columns as the pure exact-score file, plus calibration metadata:

| Column | Meaning |
|---|---|
| `calibration_strength` | Shrinkage applied to historical residuals. Current value: `0.35`. |
| `calibration_min_multiplier` | Minimum allowed score-bucket multiplier. Current value: `0.70`. |
| `calibration_max_multiplier` | Maximum allowed score-bucket multiplier. Current value: `1.35`. |

The calibrated file is useful for simulations and descriptive score probabilities. The pure file remains the cleaner representation of what the current 2026 odds imply directly.
