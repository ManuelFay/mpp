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

Process the latest snapshot:

```bash
python3 process_latest_odds.py
```

Main outputs:

- `data/odds_snapshots/latest.csv`
- `data/processed/latest_game_probabilities.csv`
- `data/processed/latest_exact_score_probabilities.csv`
- `data/processed/latest_exact_score_probabilities_calibrated.csv`

## Documentation

- [Pipeline Overview](docs/pipeline_overview.md)
- [Fetching Odds](docs/fetch_odds.md)
- [Fetching Completed Games](docs/fetch_completed_games.md)
- [Processing Latest Odds](docs/process_latest_odds.md)
- [Exact Score Model](docs/exact_score_model.md)
- [Data Layout](docs/data_layout.md)
- [Cron Usage](docs/cron.md)
- [Consistency Checks](docs/consistency_checks.md)
- [MPG Strategy](docs/mpg_strategy.md)
- [Limitations and Assumptions](docs/limitations.md)

## Current Scripts

- `fetch_odds.py`: downloads raw bookmaker odds and writes timestamped snapshots.
- `process_latest_odds.py`: reads the latest snapshot and writes game-level probabilities and exact-score probabilities.
- `compute_mpg_strategy.py`: combines MPG point payouts with result and exact-score probabilities to choose expected-value optimal picks.

## Important Notes

The exact-score probabilities are model-implied estimates, not bookmaker-published correct-score odds. The pure version is fitted from available `h2h`, `totals`, and `spreads` markets using a simple independent Poisson score model. The calibrated version applies a small historical score-shape adjustment learned from 2022 group-stage residuals.

The Odds API key is currently embedded in `fetch_odds.py` because that was requested during setup. For long-term use, moving it to an environment variable would be safer.
