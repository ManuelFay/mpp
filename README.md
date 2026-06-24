# World Cup Odds Pipeline

This project downloads FIFA World Cup 2026 group-stage odds from The Odds API, stores timestamped CSV snapshots, and converts the latest snapshot into implied game and exact-score probabilities.

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
- `data/analysis/strategy_simulations/requested_strategies/strategy_summary.csv`

## Documentation

- [Pipeline Overview](docs/pipeline_overview.md)
- [Fetching Odds](docs/fetch_odds.md)
- [Fetching Completed Games](docs/fetch_completed_games.md)
- [Data Layout](docs/data_layout.md)
- [Consistency Checks](docs/consistency_checks.md)
- [MPG Strategy and Scoring Model](docs/mpg_strategy.md)
- [Requested Strategy Analysis](docs/requested_strategy_analysis.md)

## Current Scripts

- `fetch_odds.py`: downloads raw bookmaker odds and writes timestamped snapshots.
- `fetch_completed_games.py`: fetches final scores from The Odds API scores endpoint and merges them into `data/mpg/completed_games.csv`.
- `compute_mpg_strategy.py`: processes the latest odds snapshot, combines MPG point payouts with result and exact-score probabilities, and chooses expected-value optimal picks.
- `data/analysis/strategy_simulations/analyze_requested_strategies.py`: compares fixed-score strategies, the bookmaker-injected top pick, and the current optimal strategy on completed games.

## Important Notes

The exact-score probabilities are model-implied estimates, not bookmaker-published correct-score odds. The pure version is fitted from available `h2h`, `totals`, and `spreads` markets using a simple independent Poisson score model. The calibrated version applies a small historical score-shape adjustment learned from 2022 group-stage residuals.

MPG rarity bonuses require bettor popularity rather than score probability.
`compute_mpg_strategy.py` therefore applies conservative exact-score selection
multipliers from
`data/mpg/bettor_behavior_exact_score_multipliers.csv`, then renormalizes
within each result outcome. These factors reflect observed bettor preferences
such as overweighting `2-1` and underselecting high-scoring tails. They affect
bonus tiers only; match and exact-score occurrence probabilities remain
unchanged. See [MPG Strategy and Scoring Model](docs/mpg_strategy.md#modeling-other-players).

The Odds API key is read from `ODDS_API_KEY` or a local `.odds_api_key` file.
