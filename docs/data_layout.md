# Data Layout

The project stores generated data under `data/`.

## Snapshot Data

```text
data/odds_snapshots/
  latest.csv
  YYYY/
    MM/
      world_cup_first_round_odds_YYYYMMDDTHHMMSSZ.csv
```

`latest.csv` is overwritten on every successful fetch.

Timestamped snapshots are append-only historical records. They are useful for tracking how odds change over time.

## Processed Data

```text
data/processed/
  latest_game_probabilities.csv
  latest_exact_score_probabilities.csv
  latest_exact_score_probabilities_calibrated.csv
  latest_score_shape_calibration_multipliers.csv
```

These files are overwritten when `process_latest_odds.py` runs.

If you want historical processed outputs, pass explicit output filenames, for example:

```bash
python3 process_latest_odds.py \
  --in-file data/odds_snapshots/2026/05/world_cup_first_round_odds_20260521T213826Z.csv \
  --out data/processed/game_probabilities_20260521T213826Z.csv \
  --exact-score-out data/processed/exact_scores_20260521T213826Z.csv \
  --calibrated-exact-score-out data/processed/exact_scores_calibrated_20260521T213826Z.csv
```

## Bookmaker-Injected History

```text
data/bookmaker_injected/
  bookmaker_score_odds.csv
  expected_mpg_top5.csv
```

`bookmaker_score_odds.csv` is the only bookmaker-input log. It is append-only
and stores every correct-score odd and bettor ratio for all games.

`expected_mpg_top5.csv` is the only prediction log. It is append-only and stores
five Gaussian-adjusted expected-points rows for each game submission.

Running `bookmaker_injected_strategy.py` updates both files by default.

## Completed Game Results

```text
data/mpg/completed_games.csv
```

This file stores final scores fetched from The Odds API and the realized MPG
score of the optimal strategy. Rows are merged by `event_id` and retained after
they fall outside the API's recent-results window.

See [Fetching Completed Games](fetch_completed_games.md) for the endpoint,
response schema, field mapping, and validation workflow.

## Git Ignore Policy

Raw snapshot CSV files are ignored by `.gitignore`:

```text
data/odds_snapshots/**/*.csv
data/odds_snapshots/latest.csv
```

This avoids accidentally committing large generated snapshot files.

Processed CSVs are currently not ignored. If they become large or are regenerated often, they can also be added to `.gitignore`.
