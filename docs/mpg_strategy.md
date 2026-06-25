# MPG Strategy and Scoring Model

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
- Selects round 3 by default: the next 24 schedule-sorted games after rounds
  1 and 2's first 48 games.
- Computes the expected points for every home/draw/away pick.
- Chooses the optimal result plus exact-score pick.
- Writes a round-3 comparison row for the current active strategy window.

## Run

```bash
python3 compute_mpg_strategy.py
```

Output:

```text
data/mpg/mpg_optimal_strategy.csv
data/mpg/mpg_score_expected_values.csv
data/mpg/mpg_day_comparison.csv
data/mpg/mpg_round3_top5_bets.xlsx
```

Default strategy window:

```text
event offset: 48
event limit:  24
```

This requires `data/mpg/mpg.txt` to contain the round 3 MPG point-payout rows.
The script exits with a clear error if the selected strategy window is empty.

Default comparison window:

```text
compare event offset: 48
compare event limit:  24
```

`data/mpg/mpg_day_comparison.csv` contains comparison rows for the current
round-3 strategy window. Resolved points are populated when completed results
exist in `data/mpg/completed_games.csv`.

`data/mpg/mpg_round3_top5_bets.xlsx` contains the top five result plus exact
score bets for each round-3 game, ranked by total expected points. Each row
includes outcome expected value, exact-score bonus expected value, total
expected value, predicted bonus type, bonus points, and the relevant result and
score probabilities.

To compute day 1 instead:

```bash
python3 compute_mpg_strategy.py --event-offset 0 --event-limit 24
```

To compute all remaining games:

```bash
python3 compute_mpg_strategy.py --event-offset 0 --event-limit 0
```

Every normal run also writes an immutable timestamped copy:

```text
data/mpg/strategy_snapshots/YYYY/MM/
  mpg_optimal_strategy_YYYYMMDDTHHMMSSZ.csv
  mpg_score_expected_values_YYYYMMDDTHHMMSSZ.csv
  metadata_YYYYMMDDTHHMMSSZ.json
```

The immutable files are written before the mutable latest-state outputs are
replaced. This keeps the pre-match pick and EV available after the event has
started or disappeared from later API responses.

For an intentional scratch run that should not enter history:

```bash
python3 compute_mpg_strategy.py --no-history
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

## Exact-Score Probability Model

The exact-score probabilities used by `compute_mpg_strategy.py` are computed
from the latest raw odds snapshot before the strategy is ranked. They are not
bookmaker-published correct-score odds. They are inferred from broader markets:

- `h2h`: home/draw/away.
- `totals`: over/under total goals.
- `spreads`: handicap lines.

The processor writes two versions:

- `data/processed/latest_exact_score_probabilities.csv`: pure market-implied
  Poisson model.
- `data/processed/latest_exact_score_probabilities_calibrated.csv`: the same
  model with a small historical score-shape correction.

`compute_mpg_strategy.py` uses the calibrated file by default.

### Poisson Model

The model assumes independent Poisson goal counts:

```text
home_goals ~ Poisson(home_lambda)
away_goals ~ Poisson(away_lambda)
```

For a score `h-a`:

```text
P(score = h-a) = P(home_goals = h) * P(away_goals = a)
```

Poisson is a practical baseline for football scores because it gives a full
score distribution from two stable rates. It also lets the processor compare
model probabilities against h2h, total-goals, and spread markets without extra
dependencies.

### Market Targets

Before fitting, bookmaker odds are converted into vig-removed probabilities.
Complete malformed `h2h` markets whose summed implied probability is outside
`0.85` to `1.20` are skipped.

For `h2h`, home/draw/away odds are normalized to sum to `1` per bookmaker, then
averaged across bookmakers.

For totals, over/under prices are converted into a two-way probability. The
model tries to match:

```text
P(home_goals + away_goals > total_line)
```

For integer totals, exact pushes are removed:

```text
P(over | not push) = P(total > line) / (P(total > line) + P(total < line))
```

For spreads, paired home and away handicap prices are converted into a
vig-removed home-cover probability. The model tries to match:

```text
P(home_goals + home_spread > away_goals)
```

Integer spread pushes are also conditioned out.

Quarter totals and spreads, such as `2.25` or `-1.25`, are approximated with a
single threshold. A more exact Asian-line treatment would split quarter lines
into adjacent half-stake markets.

### Fitting

The model chooses `home_lambda` and `away_lambda` to minimize weighted squared
error against:

- h2h probabilities.
- total-goals probabilities.
- spread-cover probabilities.

H2H is weighted more heavily:

```text
h2h_weight = 2.0 * sqrt(h2h_bookmaker_count)
```

Totals and spreads use:

```text
sqrt(number_of_bookmakers_for_that_line)
```

The search is a simple coordinate search over:

```text
0.05 <= lambda <= 6.0
```

For fitting market probabilities, scores from `0` to `14` goals per team are
evaluated.

### Output Grid

The exact-score CSV explicitly outputs:

```text
0-0 through 4-4
```

Everything outside that grid is aggregated into:

```text
other_probability
```

The `other` bucket is also split by result outcome:

```text
other_home_win_probability
other_draw_probability
other_away_win_probability
```

The output is normalized so:

```text
sum(score_0_0_probability ... score_4_4_probability) + other_probability = 1
```

The model-implied result probabilities are reconstructed as:

```text
model_home_win_probability = grid_home_win_probability + other_home_win_probability
model_draw_probability = grid_draw_probability + other_draw_probability
model_away_win_probability = grid_away_win_probability + other_away_win_probability
```

### Historical Score-Shape Calibration

The pure Poisson model is smooth. In comparisons against the 2022 group stage,
it underweighted some realized score buckets and over-smoothed some central
buckets. The calibrated file applies a small score-bucket correction learned
from 2022 group-stage residuals:

1. Fit a h2h-only Poisson model to every 2022 group-stage match.
2. Aggregate the model-implied `0-0` through `4-4` plus `other` distribution.
3. Aggregate the actual 2022 score distribution on the same buckets.
4. Compute `actual / expected`.
5. Shrink that ratio toward `1.0`.
6. Cap the final multiplier.

Current formula:

```text
multiplier = 1 + 0.35 * (actual / expected - 1)
multiplier = clamp(multiplier, 0.70, 1.35)
```

For each 2026 match:

```text
calibrated_score_probability = pure_score_probability * multiplier_for_score_bucket
```

All score buckets are renormalized to sum to `1`.

The learned multipliers are written to:

```text
data/processed/latest_score_shape_calibration_multipliers.csv
```

## Bookmaker-Injected Points Simulation

Script:

```text
simulate_bookmaker_injected.py
```

Run:

```bash
python3 simulate_bookmaker_injected.py
```

This runs seeded rollouts for completed games that have a logged
bookmaker-injected rank-1 pick. It writes a histogram of simulated total points
and marks the resolved points in practice plus the simulated mean.

Output:

```text
data/analysis/strategy_simulations/bookmaker_injected/top1_luck_distribution.png
data/analysis/strategy_simulations/bookmaker_injected/completed_top1_results.csv
```

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

## Model Limitations

The model is a market-implied approximation, not a complete football model.

- It assumes independent Poisson home and away goals. Real scores can have
  dependence from tactical effects, red cards, tournament incentives, and
  draw-specific behavior.
- It has only two free parameters, `home_lambda` and `away_lambda`, so it cannot
  perfectly match h2h, totals, and spreads when markets imply inconsistent
  distributions.
- It does not use bookmaker correct-score markets. If those odds are available
  from screenshots or another source, use
  `bookmaker_injected_strategy.py` instead.
- Quarter totals and quarter spreads are approximated rather than split into
  exact half-stake Asian lines.
- Bookmaker coverage varies by game. Some matches have h2h only; others also
  have totals and spreads.
- Bookmaker prices include noise from margin, stale prices, local bias,
  liquidity, and risk management. The processor removes overround within each
  market and averages across bookmakers; it does not identify sharp books.
- The historical calibration is deliberately weak because 48 group-stage
  matches from 2022 is a small sample and 2026 tournament structure differs.
