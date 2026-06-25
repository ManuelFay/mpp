# Agent Notes

Use this file as the quick operational guide for coding or data agents working
in this repository. The longer source-of-truth docs live in `docs/`.

## Python Environment

Always run project Python commands through the checked-in virtual environment:

```bash
.venv/bin/python ...
```

The system `python` may not exist, and system `python3` may not have required
packages such as `numpy` and `matplotlib`.

Examples:

```bash
.venv/bin/python compute_mpg_strategy.py
.venv/bin/python simulate_bookmaker_injected.py --include-random-player
.venv/bin/python -m unittest tests.test_analyze_bookmaker_injected_results
```

## Main Workflows

Fetch latest odds from The Odds API:

```bash
.venv/bin/python fetch_odds.py --skip-discovery
```

Compute current MPG strategy from `data/odds_snapshots/latest.csv`:

```bash
.venv/bin/python compute_mpg_strategy.py
```

This updates the processed probabilities and current strategy files:

- `data/processed/latest_game_probabilities.csv`
- `data/processed/latest_exact_score_probabilities.csv`
- `data/processed/latest_exact_score_probabilities_calibrated.csv`
- `data/mpg/mpg_optimal_strategy.csv`
- `data/mpg/mpg_score_expected_values.csv`

Fetch completed scores:

```bash
.venv/bin/python fetch_completed_games.py --days-from 3
```

Run bookmaker-injected top-1 simulations over completed games:

```bash
.venv/bin/python simulate_bookmaker_injected.py
```

Include the random-player comparison plot:

```bash
.venv/bin/python simulate_bookmaker_injected.py --include-random-player
```

Outputs are written under:

```text
data/analysis/strategy_simulations/bookmaker_injected/
```

## If The User Sends A Screenshot With Odds

When the user sends a bookmaker screenshot or pasted odds table, treat it as a
bookmaker-injected strategy request. Extract the exact-score odds and bettor
share percentages, save them to a temporary CSV, then run:

```bash
.venv/bin/python bookmaker_injected_strategy.py /tmp/input.csv
```

Do not use `--no-log` unless the user explicitly asks for a scratch calculation.
Normal runs must log both the bookmaker input and the computed top-five picks:

```text
data/bookmaker_injected/bookmaker_score_odds.csv
data/bookmaker_injected/expected_mpg_top5.csv
```

`bookmaker_score_odds.csv` is the append-only input log. It stores every pasted
correct-score odd and bettor percentage. `expected_mpg_top5.csv` is the
append-only prediction log. It stores the top five Gaussian-adjusted expected
points rows for each submission.

The input CSV should include the game metadata, exact score, decimal odds, and
bettor percentage. If the screenshot lacks home/draw/away MPG points, ask for
them before calculating. If it has a bookmaker `Other` row, keep it in the input
when available because it affects normalization.

After running the script, return the same ranked top-five table to the user.
The default bettor-share uncertainty is `sigma = 0.01`; only pass `--sigma` if
the user explicitly requests a different uncertainty.

## Scoring Facts To Preserve

Correct result earns the outcome's MPG base points. Exact score adds the rarity
bonus on top; a wrong exact score does not zero the pick if the result is right.

MPG exact-score bonus tiers:

```text
> 30%      -> 20 points
20%-30%    -> 30 points
5%-20%     -> 50 points
0.5%-5%    -> 70 points
< 0.5%     -> 100 points
```

For bookmaker-injected calculations, exact-score probabilities come from
normalized bookmaker correct-score odds, while rarity bonuses come from bettor
share among players who picked the same result outcome.

## Validation

Run focused tests after changing scoring, simulation, or plotting code:

```bash
.venv/bin/python -m unittest tests.test_analyze_bookmaker_injected_results
```

Broader validation:

```bash
.venv/bin/python -m unittest \
  tests.test_simulate_mpg_strategy \
  tests.test_analyze_bookmaker_injected_results \
  tests.test_compute_mpg_strategy
```

For a quick workflow smoke test without touching normal outputs:

```bash
.venv/bin/python data/analysis/strategy_simulations/analyze_bookmaker_injected_results.py \
  --include-random-player \
  --write-plot \
  --rollouts 1000 \
  --out-dir /tmp/mpp-bookmaker-smoke
```

## Generated Data

Many scripts overwrite latest-state CSVs and PNGs. Do not revert unrelated
generated data changes unless the user explicitly asks. Snapshot files under
`data/odds_snapshots/` and MPG strategy snapshots are historical records.

The Odds API key is read from `ODDS_API_KEY` or `.odds_api_key`.
