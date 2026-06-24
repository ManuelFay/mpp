import unittest

import fetch_completed_games


class CompletedGamesTests(unittest.TestCase):
    def test_actual_bonus_override_uses_real_mpg_payout(self) -> None:
        event = {
            "id": "ghana-panama",
            "commence_time": "2026-06-17T23:00:00Z",
            "home_team": "Ghana",
            "away_team": "Panama",
            "scores": [
                {"name": "Ghana", "score": "1"},
                {"name": "Panama", "score": "0"},
            ],
            "last_update": "2026-06-18T04:12:02Z",
        }
        strategies = {
            ("Ghana", "Panama"): {
                "optimal_pick": "Ghana",
                "optimal_exact_score": "1-0",
                "optimal_pick_points": "73",
            }
        }
        score_evs = {
            ("Ghana", "Panama", "1-0"): {
                "exact_bonus_points": "30",
            }
        }

        row = fetch_completed_games.completed_row(event, strategies, score_evs)

        self.assertEqual(row["actual_exact_bonus_points"], 20.0)
        self.assertEqual(row["total_points"], 93.0)

    def test_existing_completed_event_does_not_need_current_strategy(self) -> None:
        event = {
            "id": "round-two-event",
            "commence_time": "2026-06-23T23:00:00Z",
            "home_team": "Panama",
            "away_team": "Croatia",
            "scores": [
                {"name": "Panama", "score": "0"},
                {"name": "Croatia", "score": "1"},
            ],
            "last_update": "2026-06-24T09:25:44Z",
        }
        existing = {
            "round-two-event": {
                "event_id": "round-two-event",
                "commence_time": "2026-06-23T23:00:00Z",
                "home_team": "Panama",
                "away_team": "Croatia",
                "home_score": "0",
                "away_score": "1",
                "final_score": "0-1",
                "optimal_pick": "Draw",
                "optimal_exact_score": "1-1",
                "outcome_correct": "False",
                "exact_score_correct": "False",
                "base_points": "0.0",
                "actual_exact_bonus_points": "50.0",
                "total_points": "0.0",
                "api_last_update": "2026-06-24T09:25:44Z",
            }
        }

        merged = fetch_completed_games.merge_completed_events(
            [event],
            existing,
            strategies={},
            score_evs={},
        )

        self.assertEqual(merged["round-two-event"], existing["round-two-event"])

    def test_new_completed_event_still_requires_strategy(self) -> None:
        event = {
            "id": "new-event",
            "commence_time": "2026-06-24T21:00:00Z",
            "home_team": "Bosnia & Herzegovina",
            "away_team": "Qatar",
            "scores": [
                {"name": "Bosnia & Herzegovina", "score": "2"},
                {"name": "Qatar", "score": "0"},
            ],
        }

        with self.assertRaisesRegex(ValueError, "No optimal strategy found"):
            fetch_completed_games.merge_completed_events(
                [event],
                existing={},
                strategies={},
                score_evs={},
            )


if __name__ == "__main__":
    unittest.main()
