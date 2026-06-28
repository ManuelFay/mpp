# World Cup Odds Pipeline

This project downloads FIFA World Cup 2026 odds from The Odds API, stores timestamped CSV snapshots, and converts the latest snapshot into implied game and exact-score probabilities for MPG strategy.

## Quick Start

Install dependencies:

```bash
python3 -m pip install requests
```

Fetch the latest odds snapshot:

```bash
python3 fetch_odds.py --skip-discovery
```

Compute the MPG strategy. This also processes the latest odds snapshot into
probability CSVs:

```bash
python3 compute_mpg_strategy.py
```

Main outputs:

- `data/odds_snapshots/latest.csv`
- `data/processed/latest_game_probabilities.csv`
- `data/processed/latest_exact_score_probabilities.csv`
- `data/processed/latest_exact_score_probabilities_calibrated.csv`
- `data/mpg/completed_games.csv`
- `data/analysis/strategy_simulations/bookmaker_injected/top1_luck_distribution.png`

## Documentation

- [Pipeline Overview](docs/pipeline_overview.md)
- [Fetching Odds](docs/fetch_odds.md)
- [Fetching Completed Games](docs/fetch_completed_games.md)
- [Data Layout](docs/data_layout.md)
- [Consistency Checks](docs/consistency_checks.md)
- [MPG Strategy and Scoring Model](docs/mpg_strategy.md)
- [Requested Strategy Analysis](docs/requested_strategy_analysis.md)

## Main Scripts

- `fetch_odds.py`: downloads raw bookmaker odds and writes timestamped snapshots.
- `compute_mpg_strategy.py`: processes the latest odds snapshot, combines MPG point payouts with result and exact-score probabilities, and writes the current MPG strategy plus top-five bets.
- `fetch_completed_games.py`: fetches final scores from The Odds API scores endpoint and merges them into `data/mpg/completed_games.csv`.
- `bookmaker_injected_strategy.py`: turns pasted or screenshotted correct-score odds into bookmaker-injected MPG top-five picks and appends them to `data/bookmaker_injected/`.
- `simulate_bookmaker_injected.py`: runs by default with no arguments, simulates the bookmaker-injected top-1 strategy over completed games, and plots the points distribution with realized points and mean EV.

Most day-to-day work should use those root scripts. Deeper files under
`odds_pipeline/` and `data/analysis/` are implementation helpers or historical
analysis utilities.

## AI-Agent Usage

This repository is also intended to be used through an AI coding/data agent.
The docs describe the expected inputs, outputs, and scoring rules, so an agent
can run the root scripts or follow the documented workflow for tasks that are
not covered by a main script.

## Important Notes

The exact-score probabilities are model-implied estimates, not bookmaker-published correct-score odds. The pure version is fitted from available `h2h`, `totals`, and `spreads` markets using a simple independent Poisson score model. The calibrated version applies a small historical score-shape adjustment learned from 2022 group-stage residuals.

Round of 32 fixtures fetched between `2026-06-28T00:00:00Z` and
`2026-07-04T00:00:00Z` are tagged as `game_stage=elimination`. For these games,
90-minute market probabilities are converted to 120-minute MPG probabilities
before EV ranking: draw probability is retained by
`min(0.90, 3 * draw_probability)`, and the released draw mass is redistributed
to home and away in proportion to their 90-minute probabilities. Draw exact
scores move up one goal to the corresponding extra-time home/away winner scores.

MPG rarity bonuses require bettor popularity rather than score probability.
`compute_mpg_strategy.py` therefore applies conservative exact-score selection
multipliers from
`data/mpg/bettor_behavior_exact_score_multipliers.csv`, then renormalizes
within each result outcome. These factors reflect observed bettor preferences
such as overweighting `2-1` and underselecting high-scoring tails. They affect
bonus tiers only; match and exact-score occurrence probabilities remain
unchanged. See [MPG Strategy and Scoring Model](docs/mpg_strategy.md#modeling-other-players).

The Odds API key is read from `ODDS_API_KEY` or a local `.odds_api_key` file.
