import csv
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from fetch_odds import CSV_FIELDS, flatten_events, select_event_window, write_csv


class OddsSnapshotTests(unittest.TestCase):
    def test_select_event_window_returns_next_24_after_first_24_games(self) -> None:
        events = [
            {
                "id": f"event-{index:02d}",
                "commence_time": f"2026-06-{(index // 4) + 11:02d}T{(index % 4) * 3:02d}:00:00Z",
            }
            for index in reversed(range(60))
        ]

        selected = select_event_window(events, offset=24, limit=24)

        self.assertEqual(len(selected), 24)
        self.assertEqual(selected[0]["id"], "event-24")
        self.assertEqual(selected[-1]["id"], "event-47")

    def test_select_event_window_uses_event_id_as_stable_tiebreaker(self) -> None:
        events = [
            {"id": "b", "commence_time": "2026-06-11T12:00:00Z"},
            {"id": "a", "commence_time": "2026-06-11T12:00:00Z"},
            {"id": "c", "commence_time": "2026-06-11T15:00:00Z"},
        ]

        selected = select_event_window(events, offset=0, limit=2)

        self.assertEqual([event["id"] for event in selected], ["a", "b"])

    def test_flatten_events_tags_round_of_32_as_elimination(self) -> None:
        rows = flatten_events(
            [
                {
                    "id": "event-1",
                    "commence_time": "2026-07-04T01:30:00Z",
                    "home_team": "Home",
                    "away_team": "Away",
                    "bookmakers": [
                        {
                            "key": "book",
                            "title": "Book",
                            "last_update": "2026-06-28T12:00:00Z",
                            "markets": [
                                {
                                    "key": "h2h",
                                    "last_update": "2026-06-28T12:00:00Z",
                                    "outcomes": [
                                        {"name": "Home", "price": 2.0},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        )

        self.assertEqual(rows[0]["game_stage"], "elimination")

    def test_immutable_write_refuses_existing_snapshot(self) -> None:
        row = {field: "" for field in CSV_FIELDS}

        with TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.csv"
            write_csv([row], path, overwrite=False)

            with self.assertRaises(FileExistsError):
                write_csv([row], path, overwrite=False)

            with path.open(newline="", encoding="utf-8") as file:
                self.assertEqual(len(list(csv.DictReader(file))), 1)


if __name__ == "__main__":
    unittest.main()
