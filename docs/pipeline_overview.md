# Pipeline Overview

The project has two main stages:

1. Fetch raw bookmaker odds from The Odds API.
2. Run `compute_mpg_strategy.py`, which processes the latest raw odds snapshot
   into probability CSVs and computes MPG picks.

The MPG analysis adds two downstream stages:

3. Fetch completed scores from The Odds API scores endpoint.
4. Score and simulate MPG strategies against resolved games.

The workflow is designed for repeated execution. Each odds fetch creates a timestamped snapshot so changes in market prices can be tracked over time.

## End-to-End Flow

```text
The Odds API
  -> fetch_odds.py
  -> data/odds_snapshots/YYYY/MM/*.csv
  -> data/odds_snapshots/latest.csv
  -> compute_mpg_strategy.py
  -> data/processed/latest_game_probabilities.csv
  -> data/processed/latest_exact_score_probabilities.csv
  -> data/processed/latest_exact_score_probabilities_calibrated.csv
  -> data/mpg/mpg_optimal_strategy.csv
  -> fetch_completed_games.py
  -> data/mpg/completed_games.csv
  -> data/analysis/strategy_simulations/analyze_requested_strategies.py
  -> data/analysis/strategy_simulations/requested_strategies/
```

## Raw Snapshot

`fetch_odds.py` writes one row per event, bookmaker, market, and outcome.

Example markets:

- `h2h`: home/draw/away match result.
- `totals`: over/under total goals.
- `spreads`: handicap/spread market.

Exchange lay markets such as `h2h_lay` may be returned automatically by the API,
but `fetch_odds.py` excludes them from saved snapshots.

The default market request is:

```text
h2h,spreads,totals
```

## Processed Game Probabilities

`compute_mpg_strategy.py` first computes vig-removed implied probabilities for
each game from the `h2h` market.

For each bookmaker:

```text
raw implied probability = 1 / decimal_odds
normalized probability = raw implied probability / sum(raw implied probabilities for the market)
```

Then it averages normalized probabilities across bookmakers.

Before normalization, complete `h2h` bookmaker markets are discarded when
their summed implied probability falls outside `0.85` to `1.20`. This removes
internally inconsistent exchange quotes and other malformed market data.

## Exact Score Probabilities

The exact-score model estimates probabilities for:

```text
0-0, 0-1, ..., 4-4, other
```

The model fits two rates:

- `home_lambda`
- `away_lambda`

These rates define an independent Poisson model for home and away goals. The fitted model tries to match:

- home/draw/away probabilities from `h2h`
- over/under probabilities from `totals`
- home spread cover probabilities from `spreads`

See [MPG Strategy and Scoring Model](mpg_strategy.md#exact-score-probability-model)
for the full method.

## Score-Shape Calibration

The processor also writes a calibrated exact-score file. It starts from the market-implied Poisson model, then applies small score-bucket multipliers learned from 2022 group-stage residuals.

This is deliberately conservative:

- calibration strength is `0.35`
- each bucket multiplier is capped between `0.70` and `1.35`
- 2026 `h2h`, `totals`, and `spreads` remain the primary signal

The goal is to correct obvious score-shape artifacts, not force 2026 to reproduce 2022.

## Completed Scores

`fetch_completed_games.py` reads The Odds API scores endpoint, imports only
completed events with final scores, and merges them into
`data/mpg/completed_games.csv` by `event_id`.

See [Fetching Completed Games](fetch_completed_games.md).

## Strategy Analysis

`data/analysis/strategy_simulations/analyze_requested_strategies.py` compares fixed-score strategies, the latest
bookmaker-injected rank-1 pick, and the current expected-value optimal strategy
on completed games.

The main output is:

```text
data/analysis/strategy_simulations/requested_strategies/strategy_summary.csv
```

The per-game audit table is:

```text
data/analysis/strategy_simulations/requested_strategies/strategy_results.csv
```

See [Requested Strategy Analysis](requested_strategy_analysis.md).
