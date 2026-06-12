# MPG Strategy

Script:

```text
compute_mpg_strategy.py
```

Purpose:

- Reads MPG point payouts from `data/mpg/mpg.txt`.
- Reads market-implied result probabilities from `data/processed/latest_game_probabilities.csv`.
- Reads calibrated exact-score probabilities from `data/processed/latest_exact_score_probabilities_calibrated.csv`.
- Reads bettor-behavior multipliers from
  `data/mpg/bettor_behavior_exact_score_multipliers.csv`.
- Computes the expected points for every home/draw/away pick.
- Chooses the optimal result plus exact-score pick.

## Run

```bash
python3 compute_mpg_strategy.py
```

Output:

```text
data/mpg/mpg_optimal_strategy.csv
data/mpg/mpg_score_expected_values.csv
```

## MPG Input Format

The input file is a CSV-formatted text file:

```text
data/mpg/mpg.txt
```

Expected columns:

```text
date,time,home_team,draw,away_team,home_odds,draw_odds,away_odds,home_pct,draw_pct,away_pct
```

The script currently ignores:

```text
home_pct,draw_pct,away_pct
```

The `home_odds`, `draw_odds`, and `away_odds` columns are treated as MPG point payouts, not decimal betting odds.

## Monte Carlo Comparison With The Population

Script:

```text
simulate_mpg_strategy.py
```

Run:

```bash
python3 simulate_mpg_strategy.py
```

This runs 10,000 seeded tournament rollouts and compares one simulated
population player with the expected-value optimal strategy:

- Completed results and exact scores are read from
  `data/mpg/completed_games.csv`. Their recorded exact-score bonus is used.
- Games not yet present in that file are resolved by sampling the
  market-implied result and calibrated conditional exact-score probabilities.
- The simulated population player's result pick is sampled from
  `home_pct`, `draw_pct`, and `away_pct` in `data/mpg/mpg.txt`.
- Given that player's result pick, their selectable exact score is sampled
  proportionally from the conditional exact-score model.
- The optimal strategy is scored against the same realized results as the
  sampled population player in each rollout.

Output:

```text
data/analysis/mpg_simulation/population_vs_optimal_progress.csv
data/analysis/mpg_simulation/population_vs_optimal_final_rollouts.csv
data/analysis/mpg_simulation/population_vs_optimal_density.png
```

The plot displays a density mass of population cumulative scores by number of
games, with the optimal strategy mean and its 10th-to-90th percentile range
overlaid.

The score model explicitly represents `0-0` through `4-4`; its outcome-specific
`other` mass is included when sampling actual matches. Since it does not
identify a selectable exact score, an out-of-grid actual result can pay result
points but not an exact-score bonus in this simulation.

## Base Expected Points

For each result:

```text
base_expected_points = result_probability * result_points
```

Example:

```text
home_expected_points = home_probability * home_points
```

## Exact Score Bonus

If the selected result is correct, base points are paid. If the exact score is also correct, bonus points are added.

Important: a wrong exact score does not zero out the pick if the result is correct. The exact-score bonus is an additional boost on top of the base result points.

The bonus scale is:

| Share of correct-result players with exact score | Bonus |
|---:|---:|
| More than 30% | 20 |
| 20% to 30% | 30 |
| 5% to 20% | 50 |
| 0.5% to 5% | 70 |
| Less than 0.5% | 100 |

## Modeling Other Players

The probability of a score occurring is not the same as the share of bettors
who select it. Bettors concentrate on salient scores such as `0-0` and `2-1`
and avoid many smooth-model tail scores such as `3-2`, `4-1`, and `4-2`.

When direct bettor shares are unavailable, the script starts from the
calibrated score probabilities and applies orientation-neutral behavioral
multipliers:

```text
raw bettor weight =
    P(exact score) * bettor_behavior_multiplier(canonical score)
```

For non-draws, the canonical score is winner goals followed by loser goals:

```text
2-1 and 1-2 both use canonical score 2-1
```

Weights are renormalized within each result outcome:

```text
estimated conditional bettor share =
    adjusted score weight
    / (sum of adjusted explicit weights + outcome-specific Other mass)
```

The out-of-grid `Other` mass keeps multiplier `1.0`. Unlisted explicit scores
also default to `1.0`.

The multiplier file records conservative values derived from 10 injected
matches and 250 comparable score rows. On that sample:

- the calibrated score model was close to vig-removed correct-score odds
- bettor selections were much more concentrated than either probability model
- a held-out total-goals correction reduced bettor-share MAE by roughly 15%

The stored exact-score factors are shrunk toward `1.0` because the sample is
small, displayed bettor percentages are rounded, and many tail scores display
as zero. They are a behavioral prior, not a claim about true score frequency.

Critically:

```text
score_probability remains unchanged
result_probability remains unchanged
only the estimated bettor share used for bonus tiers is adjusted
```

To use a different calibration file:

```bash
python3 compute_mpg_strategy.py \
  --bettor-multiplier-file data/mpg/my_bettor_multipliers.csv
```

## Total Expected Points

For each result, the script chooses the exact score with the highest expected bonus:

```text
exact_bonus_expected_points = P(exact score) * bonus_points
```

Then:

```text
total_expected_points = base_expected_points + exact_bonus_expected_points
```

The CSV includes the expected boost explicitly:

```text
home_expected_boost_from_exact_score
draw_expected_boost_from_exact_score
away_expected_boost_from_exact_score
```

The optimal strategy is the result plus exact score with the highest total expected points.

## Score-Level Expected Values

The script also writes one row per game and exact score from 0-0 through 4-4:

```text
data/mpg/mpg_score_expected_values.csv
```

For every possible score, it reports:

| Column | Meaning |
|---|---|
| `score` | Exact score being evaluated. |
| `outcome` | `home`, `draw`, or `away`. |
| `outcome_probability` | Probability of the result group. |
| `score_probability` | Probability of that exact score. |
| `score_model_conditional_probability` | Raw model score probability conditional on the result group, including Other mass. |
| `score_conditional_probability` | Behavior-adjusted conditional bettor share used for the MPG bonus tier. |
| `outcome_points` | MPG points for getting the result right. |
| `base_expected_points` | Result EV, paid whenever the result is right. |
| `exact_bonus_label` | Bonus tier inferred from conditional score probability. |
| `exact_bonus_points` | Bonus points if the exact score is right. |
| `exact_bonus_expected_points` | Expected boost from the exact-score bonus. |
| `total_expected_points` | Base EV plus exact-score boost EV. |

This table is useful for inspecting whether a lower-probability result can become optimal because its best exact score has a stronger expected boost.

## Current Result

With the current `data/mpg/mpg.txt`:

```text
MPG games processed: 24
Score EV rows written: 600
Total expected points: 855.36
Strategies changed by exact-score bonus: 2
```

The changed games are:

| Game | Base-only pick | Pick with exact-score bonus | Exact score |
|---|---|---|---|
| `Spain vs Cape Verde` | `Draw` | `Spain` | `2-0` |
| `Iran vs New Zealand` | `Draw` | `Iran` | `1-0` |

## Important Assumptions

- Exact-score probabilities use the calibrated 2026 score model.
- Other-player exact-score shares use the stored bettor-behavior multipliers.
- The multipliers estimate selection behavior only and do not alter score probabilities.
- The multiplier calibration currently uses a small sample of 10 injected matches.
- The script only chooses explicit 0-0 through 4-4 exact scores.
- The `other` bucket cannot be selected as an exact score.
- This is expected-value optimal, not risk-adjusted. A player trying to maximize tournament rank rather than expected points may prefer more volatile picks.
