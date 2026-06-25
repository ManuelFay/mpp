# Strategy Simulations

This directory contains historical and specialist simulation helpers. Normal
usage should start from the root scripts documented in `README.md`, especially
`simulate_bookmaker_injected.py` for the bookmaker-injected distribution plot.
Generated outputs are intentionally not kept here by default: summaries, result
tables, raw rollout CSVs, pasted input CSVs, and PNG plots can all be
regenerated when needed.

## Scripts

- `analyze_bookmaker_injected_results.py`: implementation helper used by the
  root `simulate_bookmaker_injected.py` script.
- `analyze_requested_strategies.py`: historical comparison of fixed exact-score
  strategies, bookmaker-injected picks, and the EV-optimal strategy.
- `simulate_mpg_strategy.py`: historical comparison of the EV-optimal MPG
  strategy against a representative sampled player.

## Durable Inputs

The durable bookmaker-injected logs live outside this directory:

- `data/bookmaker_injected/bookmaker_score_odds.csv`
- `data/bookmaker_injected/expected_mpg_top5.csv`

Completed game results live in:

- `data/mpg/completed_games.csv`

One-off per-country/per-match bookmaker input CSVs, pasted strategies, bet
input files, rollout CSVs, and PNG plots are disposable and should not be
committed.
