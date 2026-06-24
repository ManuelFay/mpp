# Limitations and Assumptions

The exact-score model is a useful market-implied approximation, not a complete betting model.

## Independent Poisson Assumption

The model assumes:

```text
home_goals and away_goals are independent Poisson variables
```

Real football scores are not perfectly independent. Draw probabilities, low-score dependence, tactical effects, red cards, and tournament incentives can all violate this assumption.

## Only Two Free Parameters

The model fits only:

```text
home_lambda
away_lambda
```

That means it cannot perfectly match every h2h, total, and spread market when those markets imply inconsistent distributions.

Symptoms:

- h2h fits are usually tight
- totals are usually acceptable
- spreads can have larger errors

## No Correct-Score Market Data

The Odds API snapshot does not include bookmaker correct-score odds. The exact-score probabilities are inferred from broader markets.

If correct-score odds become available from another source, they should be incorporated directly.

## Quarter Lines Are Approximate

Asian quarter totals and spreads, such as:

```text
2.25
-1.25
```

are currently handled as a single threshold.

More exact treatment would split quarter lines into two half-stake markets:

```text
2.25 = half on 2.0 + half on 2.5
-1.25 = half on -1.0 + half on -1.5
```

This would improve totals and spreads consistency.

## Bookmaker Coverage Is Uneven

Not every game has all markets.

Possible cases:

- h2h only
- h2h plus totals
- h2h plus totals and spreads

The API may return exchange lay markets such as `h2h_lay`, but the fetcher and
processors exclude them. The exact-score model uses the remaining available
markets.

## Other Bucket Is Aggregated

The output explicitly lists 0-0 through 4-4. Everything else is grouped into:

```text
other_probability
```

Because `other` includes home wins, draws, and away wins, the CSV also includes:

```text
other_home_win_probability
other_draw_probability
other_away_win_probability
```

Use those columns when reconstructing h2h probabilities from the exact-score file.

## Market Prices Include Noise

Bookmaker odds can differ because of:

- different margins
- stale prices
- different risk management
- sparse markets
- local bookmaker bias
- exchange liquidity differences

The processor removes overround within each market, then averages across bookmakers. It does not try to identify sharp bookmakers or remove stale books.

## Historical Calibration Is Deliberately Weak

The calibrated exact-score output uses 2022 group-stage residuals to adjust score buckets. This helps correct some obvious Poisson score-shape artifacts, but the calibration is intentionally small:

```text
strength = 0.35
min multiplier = 0.70
max multiplier = 1.35
```

Reasons:

- 48 group-stage matches from 2022 is a small sample.
- 2026 has a larger field and is expected to contain more asymmetric games.
- The current 2026 odds, totals, and spreads should remain the dominant signal.

Use the calibrated file for simulations where historical score shape matters. Use the pure file when you want a cleaner market-implied model.

## API Key Handling

The API key is loaded from `ODDS_API_KEY` or the local `.odds_api_key` file.

For safer long-term operation, prefer an environment variable:

```bash
export ODDS_API_KEY="..."
```

and update the script to read from `os.environ`.
