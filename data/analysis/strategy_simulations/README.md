# Strategy Simulations

This directory contains reusable simulation scripts. Generated simulation
outputs are intentionally not kept here by default: summaries, result tables,
raw rollout CSVs, pasted input CSVs, and PNG plots can all be regenerated when
needed.

## Scripts

- `analyze_bookmaker_injected_results.py`: scores the latest bookmaker-injected
  rank-1 picks against completed games and estimates the strategy distribution.
- `analyze_requested_strategies.py`: compares fixed exact-score strategies,
  the bookmaker-injected top pick, and the current EV-optimal strategy.
- `simulate_mpg_strategy.py`: compares the EV-optimal MPG strategy against a
  representative player sampled from the published MPG pick distribution.

## Durable Inputs

The durable bookmaker-injected logs live outside this directory:

- `data/bookmaker_injected/bookmaker_score_odds.csv`
- `data/bookmaker_injected/expected_mpg_top5.csv`

Completed game results live in:

- `data/mpg/completed_games.csv`

One-off per-country/per-match bookmaker input CSVs, pasted strategies, bet
input files, rollout CSVs, and PNG plots are disposable and should not be
committed.
