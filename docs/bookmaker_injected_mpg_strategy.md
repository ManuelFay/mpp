# Bookmaker-Injected MPG Exact Score Strategy

This workflow replaces the internally calculated exact-score probabilities and
bettor distributions with values injected directly from bookmaker screens.

Use it when you have:

- correct-score odds from a bookmaker
- bettor share percentages for each exact score
- MPG outcome points for home, draw, and away

The output is a ranked list of exact scores to predict, with expected value and
bonus category.

## Inputs

For each listed exact score, collect:

```text
score, decimal_odds, bettor_share_percent
```

Example:

```text
1-0, 4.90, 13
0-0, 8.00, 21
2-0, 5.20, 13
```

The `bettor_share_percent` is not a probability of the score happening. It is
the share of bettors who selected that exact score.

You also need the MPG outcome points:

```text
home_points, draw_points, away_points
```

Example:

```text
Mexico: 49
Draw: 125
South Africa: 148
```

## Step 1: Convert Odds To Score Probabilities

Convert each correct-score decimal odd into raw implied probability:

```text
raw_score_probability = 1 / decimal_odds
```

Correct-score markets usually contain heavy overround, so normalize across all
listed scores:

```text
normalized_score_probability = raw_score_probability / sum(all raw_score_probabilities)
```

Use this normalized score probability as the real score probability for EV.

## Step 2: Assign Each Score To An Outcome

Map each score into an outcome bucket:

```text
home win: home_goals > away_goals
draw:     home_goals = away_goals
away win: home_goals < away_goals
```

Example:

```text
2-0 -> home win
1-1 -> draw
0-1 -> away win
```

## Step 3: Calculate Conditional Bettor Share

MPG rarity depends on the share of bettors who picked the exact score among
bettors who picked the correct outcome, not among all bettors.

For a given score:

```text
conditional_bettor_share =
    score_bettor_share / sum(bettor_share for all scores in same outcome bucket)
```

Example for Mexico home wins:

```text
1-0: 13%
2-0: 13%
2-1: 11%
3-0: 3%
3-1: 4%
3-2: 0%
4-0: 0%

total home-win bettor share = 44%

2-0 conditional bettor share = 13 / 44 = 29.55%
```

## Step 4: Convert Conditional Share To Bonus Category

Use the same thresholds as `compute_mpg_strategy.py`:

```text
Exact       > 30%      -> 20 points
Rare        20%-30%    -> 30 points
Tres rare   5%-20%     -> 50 points
Mega rare   0.5%-5%    -> 70 points
Ultra rare  < 0.5%     -> 100 points
```

The category is driven by bettor distribution, not by bookmaker probability.

### Account For Bettor-Share Uncertainty

Treat the calculated conditional bettor share as the center of a Gaussian
distribution instead of as an exact final value:

```text
final_conditional_share ~ Normal(calculated_conditional_share, 0.01)
```

The default standard deviation is `0.01`, meaning one percentage point. This is
small enough to affect scores near a bonus boundary without materially changing
scores far from a boundary.

Do not randomly sample this distribution. Calculate the probability mass in
each bonus tier with the normal CDF, then calculate:

```text
expected_bonus_points =
    P(share < 0.5%)         * 100
  + P(0.5% <= share < 5%)  * 70
  + P(5% <= share < 20%)   * 50
  + P(20% <= share <= 30%) * 30
  + P(share > 30%)         * 20
```

For example, a calculated share of `19.6%` still has a meaningful probability
of finishing at or above `20%`. Its expected bonus is therefore lower than the
nominal 50-point bonus.

Keep the nominal bonus in the output for readability, but use
`expected_bonus_points` in all EV calculations. A different sigma may be used
when explicitly requested; `0.01` is the default.

## Step 5: Calculate Expected Value

For games tagged `game_stage=elimination` in
`data/processed/latest_game_probabilities.csv`, first convert the 90-minute
home/draw/away probabilities into 120-minute MPG probabilities:

```text
draw_retention_factor = min(0.90, 3 * draw_probability)
corrected_draw_probability = draw_probability * draw_retention_factor
released_draw_mass = draw_probability - corrected_draw_probability
```

The released draw mass is added to home and away in proportion to their
90-minute probabilities. Correct-score odds are adjusted the same way: each
draw score `N-N` keeps the retained mass, and the released mass moves only to
`(N+1)-N` or `N-(N+1)`. For example, `1-1` can move to `2-1` or `1-2`, never to
`1-0` or `0-1`.

By default, bookmaker-injected runs now report and log two elimination-game
variants:

- `no_transfer`: bettor shares remain exactly as displayed in the source table.
- `transfer`: draw bettor shares are shifted through the same `N-N` to
  `(N+1)-N` / `N-(N+1)` transition before rarity tiers are calculated.

Both variants use the same adjusted outcome and exact-score probabilities. The
only difference is whether rarity bonuses use displayed bettor shares or
extra-time-transferred bettor shares.

For each exact score:

```text
base_outcome_ev = outcome_probability * outcome_mpg_points
exact_bonus_ev = normalized_score_probability * expected_bonus_points
total_ev = base_outcome_ev + exact_bonus_ev
```

If you already have bookmaker-implied 1X2 probabilities, use those for
`outcome_probability`.

If you only have correct-score odds, you can estimate outcome probability by
summing normalized score probabilities within the outcome bucket:

```text
home_probability = sum(normalized probabilities for home-win scores)
draw_probability = sum(normalized probabilities for draw scores)
away_probability = sum(normalized probabilities for away-win scores)
```

If the correct-score table has an `Other` row, decide how to allocate it before
using this method for outcome probabilities. If you cannot allocate it, prefer
using the bookmaker 1X2 market for outcome probabilities.

## Step 6: Rank Scores

Rank all score candidates by:

```text
total_ev descending
```

If two scores have the same `total_ev` when rounded to two decimals, choose the
safer score using these tie-breakers in order:

```text
1. lower standard deviation of the full MPG payoff
2. higher outcome probability
3. higher exact-score probability
```

The top rows are the best exact-score predictions under this injected
bookmaker/bettor setup.

The full payoff variance includes the chance of receiving zero points, only the
outcome payout, or the outcome payout plus the uncertain exact-score bonus.

## Calculator

Save pasted bookmaker rows as CSV, then run:

```bash
python3 bookmaker_injected_strategy.py input.csv
```

Every normal run is logged automatically:

```text
data/bookmaker_injected/bookmaker_score_odds.csv
data/bookmaker_injected/expected_mpg_top5.csv
```

`bookmaker_score_odds.csv` is the single append-only input log for all games. It
stores every pasted exact-score odd and bettor percentage. Each invocation gets
one `submission_id`, so repeated odds for the same game remain separate
submissions instead of being overwritten or deduplicated.

`expected_mpg_top5.csv` is the single append-only output log for all games. It
stores five rows per game submission, including:

- rank and exact score
- outcome and exact-score probabilities
- conditional bettor share and Gaussian sigma
- nominal and expected bonus points
- base, exact-score, and total expected MPG points
- payoff standard deviation and best-pick indicator

When bookmaker odds are pasted in chat, first persist the rows and prediction
through this logging workflow, then return the same table to the user. Do this
without requiring a separate logging request.

Optional uncertainty override:

```bash
python3 bookmaker_injected_strategy.py input.csv --sigma 0.015
```

Choose a bettor-share transfer mode explicitly:

```bash
python3 bookmaker_injected_strategy.py input.csv --bettor-share-transfer both
python3 bookmaker_injected_strategy.py input.csv --bettor-share-transfer off
python3 bookmaker_injected_strategy.py input.csv --bettor-share-transfer on
```

The default is `both`. The prediction log stores the variant in
`bettor_share_transfer`.

For an intentional scratch calculation that should not enter the history:

```bash
python3 bookmaker_injected_strategy.py input.csv --no-log
```

## Required Output Format

When correct-score odds and bettor percentages are pasted as CSV or a Markdown
table, produce one section per game. Show the five exact scores with the highest
`total_ev`, sorted from highest to lowest.

Use this table format:

| Rank | Exact score | Outcome probability | Exact-score probability | Conditional bettor share | Bonus | Expected bonus | Base EV | Exact-score EV | Total EV |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | Home team 2-0 | 00.00% | 00.00% | 00.00% | 50 pts | 00.00 pts | 00.00 | 00.00 | **00.00** |
| 2 | Draw 1-1 | 00.00% | 00.00% | 00.00% | 30 pts | 00.00 pts | 00.00 | 00.00 | **00.00** |
| 3 | Away team 0-1 | 00.00% | 00.00% | 00.00% | 70 pts | 00.00 pts | 00.00 | 00.00 | **00.00** |
| 4 | Home team 1-0 | 00.00% | 00.00% | 00.00% | 20 pts | 00.00 pts | 00.00 | 00.00 | **00.00** |
| 5 | Away team 1-2 | 00.00% | 00.00% | 00.00% | 100 pts | 00.00 pts | 00.00 | 00.00 | **00.00** |

Column definitions:

- `Outcome probability`: probability of home win, draw, or away win from the
  current game-probability data.
- `Exact-score probability`: normalized probability derived from all supplied
  correct-score decimal odds, including the `Other` row in the normalization
  denominator.
- `Conditional bettor share`: displayed bettor percentage for the score divided
  by the total displayed bettor percentage for scores with the same outcome.
- `Bonus`: nominal MPG exact-score bonus at the calculated conditional share.
- `Expected bonus`: Gaussian-adjusted expected bonus across all bonus tiers.
- `Base EV`: outcome probability multiplied by the MPG payout for that outcome.
- `Exact-score EV`: exact-score probability multiplied by the expected bonus.
- `Total EV`: `Base EV + Exact-score EV`.

Formatting rules:

- Display probabilities and bettor shares as percentages with two decimals.
- Display EV values with two decimals.
- Bold the `Total EV` values.
- Label home and away scores with the relevant team name. Label draws as
  `Draw X-X`.
- After each table, state `Best pick: <exact score>`, and mention when the top
  candidates are separated by less than one expected point.
- If multiple games are pasted, ignore rows for previously analyzed games only
  when the user explicitly identifies which new game to process. Otherwise,
  produce a separate table for every game in the pasted input.
- Report malformed inputs or bettor-percentage totals that indicate inconsistent
  source data.

## Worked Example: Mexico vs South Africa

Assumptions:

- real exact-score probabilities come from normalized bookmaker correct-score odds
- rarity categories come from displayed bettor share percentages
- MPG outcome probabilities and points come from `data/mpg/mpg_optimal_strategy.csv`

Outcome base EV:

```text
Mexico:       0.666353 * 49  = 32.65
Draw:         0.215602 * 125 = 26.95
South Africa: 0.118045 * 148 = 17.47
```

Mexico-win conditional bettor shares:

The displayed home-win bettor percentages total `95%`, so each home-win score
is divided by `95` to get its conditional share. The one-percentage-point
Gaussian adjustment is then applied around that share.

| Score | Bettor % | Conditional share | Nominal bonus | Expected bonus |
|---:|---:|---:|---:|---:|
| 1-0 | 10% | 10.53% | 50 | 50.00 |
| 2-0 | 26% | 27.37% | 30 | 29.96 |
| 2-1 | 25% | 26.32% | 30 | 30.00 |
| 3-0 | 6% | 6.32% | 50 | 51.88 |
| 3-1 | 9% | 9.47% | 50 | 50.00 |
| 3-2 | 3% | 3.16% | 70 | 69.46 |
| 4-0 | 7% | 7.37% | 50 | 50.18 |

Gaussian-adjusted top five:

| Rank | Exact score | Outcome probability | Exact-score probability | Conditional bettor share | Bonus | Expected bonus | Base EV | Exact-score EV | Total EV |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | Mexico 1-0 | 66.64% | 13.82% | 10.53% | 50 | 50.00 | 32.65 | 6.91 | **39.56** |
| 2 | Mexico 3-0 | 66.64% | 8.66% | 6.32% | 50 | 51.88 | 32.65 | 4.49 | **37.15** |
| 3 | Mexico 2-0 | 66.64% | 12.99% | 27.37% | 30 | 29.96 | 32.65 | 3.89 | **36.54** |
| 4 | Mexico 3-1 | 66.64% | 5.41% | 9.47% | 50 | 50.00 | 32.65 | 2.71 | **35.36** |
| 5 | Mexico 2-1 | 66.64% | 8.12% | 26.32% | 30 | 30.00 | 32.65 | 2.44 | **35.09** |

**Best pick: Mexico 1-0.**

## Important Caveats

Displayed bettor percentages may be rounded. A displayed `0%` may mean a small
positive share, not literally zero. This matters because the difference between
`0.4%` and `0.6%` changes the bonus from `Ultra rare` to `Mega rare`.

Correct-score odds are high-margin markets. Always normalize implied
probabilities before using them as real probabilities.

If a bookmaker only lists some exact scores plus `Other`, the `Other` row can
hide meaningful probability mass. Do not ignore it when comparing total market
shape.

The method is best used for ranking exact-score choices inside MPG. It should
not be interpreted as a clean betting edge unless the bookmaker margin,
rounding, and missing score mass are handled carefully.
