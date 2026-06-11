# Exact Score Model

The exact-score output is produced by fitting a simple score model to the available odds markets.

The model is intentionally lightweight and dependency-free. It does not use bookmaker-published correct-score odds. It infers score probabilities from:

- `h2h`: home/draw/away
- `totals`: over/under total goals
- `spreads`: handicap lines

The processor writes two exact-score versions:

- `latest_exact_score_probabilities.csv`: pure market-implied Poisson model.
- `latest_exact_score_probabilities_calibrated.csv`: pure model with a small historical score-shape correction.

## Output Scores

The CSV includes explicit probabilities for:

```text
0-0 through 4-4
```

and one aggregate bucket:

```text
other
```

`other` means any final score outside the 0-0 to 4-4 grid, such as:

- 5-0
- 0-5
- 5-5
- 6-2
- any higher score combination

## Model Form

The model assumes independent Poisson goal counts:

```text
home_goals ~ Poisson(home_lambda)
away_goals ~ Poisson(away_lambda)
```

For a score `h-a`:

```text
P(score = h-a) = P(home_goals = h) * P(away_goals = a)
```

This imposes a smooth, continuous, concave-ish score shape:

- very low and very high scores are less likely
- probabilities decline smoothly away from each team mean
- total-goal probabilities are monotone in the total line
- stronger favorites receive higher expected goals

## Why Poisson

Poisson is a common baseline model for football scores because:

- scores are non-negative integers
- most football scores are low
- a two-rate model is simple and stable
- it gives a full probability distribution over all exact scores
- totals and spread probabilities can be computed from the score grid

It is not perfect. See [Limitations and Assumptions](limitations.md).

## Market Targets

Before fitting, bookmaker odds are converted into vig-removed probabilities.

### H2H

For each bookmaker, home/draw/away decimal odds are converted to implied probabilities and normalized so they sum to 1.

The averaged values become the target:

```text
target_home_win
target_draw
target_away_win
```

### Totals

For each bookmaker and total line:

```text
Over price
Under price
```

are converted into two-way vig-removed probabilities.

The model computes:

```text
P(home_goals + away_goals > total_line)
```

and tries to match the market-implied over probability.

If the line is an integer, such as 2.0, an exact total of 2 is a push. The script treats the market as conditional on no push:

```text
P(over | not push) = P(total > line) / (P(total > line) + P(total < line))
```

For half lines, such as 2.5, there is no push.

For quarter lines, such as 2.25, the current implementation uses the same threshold comparison. This is an approximation. A more exact Asian total treatment would split 2.25 into half stakes on 2.0 and 2.5.

### Spreads

For each bookmaker and spread line, the script pairs the home and away spread prices.

Example:

```text
Mexico -1.0
South Africa +1.0
```

The two prices are converted into a vig-removed home-cover probability.

The model computes:

```text
P(home_goals + home_spread > away_goals)
```

and tries to match the market-implied home-cover probability.

If the spread is an integer, a tie after handicap is a push. The script conditions on no push:

```text
P(home cover | not push)
```

Quarter spreads are currently approximated with a single threshold. A more exact Asian handicap treatment would split quarter lines into adjacent half lines.

## Fitting Objective

The model chooses `home_lambda` and `away_lambda` to minimize weighted squared error between model probabilities and market-implied targets.

The loss includes:

```text
h2h errors
totals errors
spread errors
```

H2H is weighted more heavily:

```text
h2h_weight = 2.0 * sqrt(h2h_bookmaker_count)
```

Totals and spreads use:

```text
sqrt(number_of_bookmakers_for_that_line)
```

This gives more influence to lines supported by more bookmakers while avoiding one large bookmaker count completely dominating the fit.

## Search Method

The script uses a simple coordinate search:

1. Build an initial guess for `home_lambda` and `away_lambda`.
2. Try neighboring lambda pairs.
3. Keep improvements.
4. Reduce step size.
5. Stop when step size is below `0.01`.

Bounds:

```text
0.05 <= lambda <= 6.0
```

No external optimizer is required.

## Model Grid

For fitting market probabilities, the model evaluates scores from:

```text
0 to 14 goals per team
```

This is controlled by:

```text
MODEL_MAX_GOALS = 14
```

For output, explicit exact scores are limited to:

```text
0 to 4 goals per team
```

This is controlled by:

```text
SCORE_GRID_MAX = 4
```

Everything outside 0-4 by 0-4 is aggregated into `other_probability`.

## Exact Score CSV Columns

Key columns:

| Column | Meaning |
|---|---|
| `home_lambda` | Fitted home expected goals. |
| `away_lambda` | Fitted away expected goals. |
| `model_home_win_probability` | Full fitted model home win probability. |
| `model_draw_probability` | Full fitted model draw probability. |
| `model_away_win_probability` | Full fitted model away win probability. |
| `grid_home_win_probability` | Home win probability inside 0-0 through 4-4 only. |
| `grid_draw_probability` | Draw probability inside 0-0 through 4-4 only. |
| `grid_away_win_probability` | Away win probability inside 0-0 through 4-4 only. |
| `other_home_win_probability` | Home win probability outside the explicit grid. |
| `other_draw_probability` | Draw probability outside the explicit grid. |
| `other_away_win_probability` | Away win probability outside the explicit grid. |
| `model_loss` | Weighted squared-error objective value after fitting. |
| `score_H_A_probability` | Probability of exact score H-A for H and A from 0 to 4. |
| `other_probability` | Probability of any score outside 0-0 through 4-4. |

## Normalization

The output is normalized as:

```text
sum(score_0_0_probability ... score_4_4_probability) + other_probability = 1
```

Also:

```text
other_home_win_probability
+ other_draw_probability
+ other_away_win_probability
= other_probability
```

The model-implied h2h probabilities are:

```text
model_home_win_probability = grid_home_win_probability + other_home_win_probability
model_draw_probability = grid_draw_probability + other_draw_probability
model_away_win_probability = grid_away_win_probability + other_away_win_probability
```

## Historical Score-Shape Calibration

The pure Poisson model is smooth. In comparisons against the 2022 group stage, it underweighted some realized score buckets such as `0-2` and over-smoothed some central buckets. To correct this gently, the processor can produce a calibrated version.

Calibration is learned from 2022 group-stage matches:

1. Fit a h2h-only Poisson model to every 2022 group-stage match.
2. Aggregate the model-implied 0-0 through 4-4 plus `other` distribution.
3. Aggregate the actual 2022 group-stage score distribution on the same buckets.
4. Compute `actual / expected` for each score bucket.
5. Shrink that ratio strongly toward `1.0`.
6. Cap the final multiplier.

The current formula is:

```text
multiplier = 1 + 0.35 * (actual / expected - 1)
multiplier = clamp(multiplier, 0.70, 1.35)
```

Then, for each 2026 match:

```text
calibrated_score_probability = pure_score_probability * multiplier_for_score_bucket
```

All score buckets are renormalized so probabilities sum to 1.

This intentionally applies only a small correction. The 2026 tournament has more teams and likely more asymmetric matches than 2022, so the calibration should not fully force the 2026 distribution to look historical.

The learned multipliers are written to:

```text
data/processed/latest_score_shape_calibration_multipliers.csv
```
