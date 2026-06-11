# Consistency Checks

This page describes the checks used to verify the processed probability outputs.

## Normalization

For each row in `latest_exact_score_probabilities.csv`:

```text
sum(score_0_0_probability ... score_4_4_probability) + other_probability = 1
```

The `other` split should also satisfy:

```text
other_home_win_probability
+ other_draw_probability
+ other_away_win_probability
= other_probability
```

## H2H Consistency

The model-implied h2h probabilities should be close to the market-implied h2h probabilities:

```text
model_home_win_probability ~= home_probability
model_draw_probability ~= draw_probability
model_away_win_probability ~= away_probability
```

The game-level market probabilities are in:

```text
data/processed/latest_game_probabilities.csv
```

The model probabilities are in:

```text
data/processed/latest_exact_score_probabilities.csv
```

## Totals Consistency

For each totals line, the fitted model can compute:

```text
P(home_goals + away_goals > total_line)
```

For integer lines, the check should condition on no push:

```text
P(over | not push)
```

The result should be close to the vig-removed market-implied over probability.

## Spread Consistency

For each spread line, the fitted model can compute:

```text
P(home_goals + home_spread > away_goals)
```

For integer spread lines, the check should condition on no push.

The result should be close to the vig-removed market-implied home-cover probability.

## Recent Audit Result

Using the current all-market snapshot:

```text
Rows: 72
Max score + other mass error: 0.000000000000
Max other split error:       0.000000000000

H2H model vs market:
avg abs error 0.71pp
median abs error 0.54pp
p90 abs error 1.52pp
max abs error 5.23pp

Totals over model vs market:
avg abs error 1.72pp
median abs error 0.86pp
p90 abs error 4.77pp
max abs error 7.19pp

Spreads home-cover model vs market:
avg abs error 2.17pp
median abs error 1.24pp
p90 abs error 5.89pp
max abs error 10.82pp
```

The exact score probabilities are normalized exactly. H2H is represented well overall. Totals are reasonably represented. Spreads are the weakest fit, mostly because a two-parameter independent Poisson model cannot perfectly satisfy all h2h, total, and spread markets when they disagree.

## Score-Shape Calibration Check

The historical score-shape calibration was compared against actual 2022 group-stage score buckets:

```text
Total variation distance vs 2022 group-stage actuals:

2026 pure Poisson:   0.298
2026 calibrated:     0.221
2022 h2h Poisson:    0.262
```

This means the calibrated 2026 score-bucket distribution is closer to 2022 history than the pure model, but the correction is intentionally modest. The calibration caps each score-bucket multiplier between `0.70` and `1.35`.

Comparison outputs:

```text
data/analysis/score_shape_calibration_comparison.csv
data/analysis/score_shape_calibration_metrics.csv
data/analysis/plots/score_shape_calibration_comparison.png
```

## Suggested Audit Script

For repeated work, it would be useful to promote the ad-hoc audit into a script such as:

```text
audit_processed_odds.py
```

That script should:

- read `data/odds_snapshots/latest.csv`
- read `data/processed/latest_game_probabilities.csv`
- read `data/processed/latest_exact_score_probabilities.csv`
- compute normalization errors
- recompute h2h, totals, and spreads from fitted lambdas
- report average, median, p90, and max absolute errors
