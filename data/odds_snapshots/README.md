# Odds Snapshots

Timestamped odds CSV snapshots are written here.

Default layout:

```text
data/odds_snapshots/
  latest.csv
  YYYY/
    MM/
      world_cup_first_round_odds_YYYYMMDDTHHMMSSZ.csv
```

The timestamp is UTC, so cron runs from any local timezone sort correctly by filename.

Example cron entry, running every six hours:

```cron
0 */6 * * * cd /home/manu/mpp && /home/manu/mpp/.venv/bin/python fetch_odds.py --skip-discovery >> data/odds_snapshots/fetch.log 2>&1
```
