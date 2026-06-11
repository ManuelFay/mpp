# Cron Usage

The pipeline is designed to run regularly.

## Fetch Only

Run every six hours:

```cron
0 */6 * * * cd /home/manu/mpp && /home/manu/mpp/.venv/bin/python fetch_odds.py --skip-discovery >> data/odds_snapshots/fetch.log 2>&1
```

This creates timestamped raw snapshots and updates `latest.csv`.

## Fetch and Process

Run every six hours and process immediately after a successful fetch:

```cron
0 */6 * * * cd /home/manu/mpp && /home/manu/mpp/.venv/bin/python fetch_odds.py --skip-discovery >> data/odds_snapshots/fetch.log 2>&1 && /home/manu/mpp/.venv/bin/python process_latest_odds.py >> data/processed/process.log 2>&1
```

## Recommended Cron Notes

- Use absolute paths.
- Redirect logs to files.
- Use `--skip-discovery` to save one API call.
- Keep the fetch and process steps chained with `&&` so processing only happens after a successful fetch.
- Monitor API credit usage in `fetch.log`.

## Historical Processed Files

The default processor overwrites:

```text
data/processed/latest_game_probabilities.csv
data/processed/latest_exact_score_probabilities.csv
data/processed/latest_exact_score_probabilities_calibrated.csv
```

If you want processed files for every snapshot, use a wrapper script that extracts the timestamp from the newest snapshot filename and passes timestamped `--out` and `--exact-score-out` paths.
