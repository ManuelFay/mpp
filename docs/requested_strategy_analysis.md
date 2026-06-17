# Requested Strategy Analysis

`data/analysis/strategy_simulations/analyze_requested_strategies.py` compares fixed exact-score strategies against
resolved games, then simulates each strategy's expected total-point
distribution.

## Command

Update completed results first:

```bash
.venv/bin/python fetch_completed_games.py --days-from 3
```

Then run the strategy analysis:

```bash
.venv/bin/python data/analysis/strategy_simulations/analyze_requested_strategies.py
```

The default run uses 200,000 rollouts per strategy.

For a quick smoke run:

```bash
.venv/bin/python data/analysis/strategy_simulations/analyze_requested_strategies.py \
  --rollouts 1000 \
  --out-dir /tmp/mpp-requested-strategies-smoke
```

## Strategies

The script evaluates:

- `always_0_0`: always pick `0-0`.
- `always_1_1`: always pick `1-1`.
- `underdog_1_0`: pick the lower-probability non-draw team to win 1-0.
- `favorite_1_0`: pick the higher-probability non-draw team to win 1-0.
- `bookmaker_injected_top1`: use the latest logged rank-1 bookmaker-injected pick.
- `optimal_current`: use the current expected-value optimal exact score from `data/mpg/mpg_optimal_strategy.csv`.

For away-team 1-0 selections, the stored exact score is `0-1` because scores
are recorded home-away.

## Inputs

Default inputs:

```text
data/mpg/completed_games.csv
data/mpg/mpg_score_expected_values.csv
data/mpg/mpg_optimal_strategy.csv
data/bookmaker_injected/expected_mpg_top5.csv
data/mpg/mpg.txt
```

The analysis scores only completed games. It uses the same MPG rule as the
other simulation scripts: a correct result earns the selected outcome's MPG
points, and an exact score adds the score's rarity bonus.

## Outputs

Default output directory:

```text
data/analysis/strategy_simulations/requested_strategies/
```

Files:

- `strategy_summary.csv`: one row per strategy with realized points, expected points, simulated mean and standard deviation, percentile, and quantiles.
- `strategy_results.csv`: per-game scoring details for every strategy.

Raw rollout CSVs and PNG plots are disposable render outputs and are not
retained by default.

Use `strategy_results.csv` when a total looks surprising. For example, an
`always_1_1` pick earns draw points on any draw and adds the exact-score bonus
only when the final score is exactly `1-1`.

## Validation

Run the core tests after changing scoring code:

```bash
.venv/bin/python -m unittest \
  tests.test_simulate_mpg_strategy \
  tests.test_analyze_bookmaker_injected_results \
  tests.test_compute_mpg_strategy
```

Compile the two workflow scripts:

```bash
.venv/bin/python -m py_compile \
  fetch_completed_games.py \
  data/analysis/strategy_simulations/analyze_requested_strategies.py
```
