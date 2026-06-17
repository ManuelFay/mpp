import unittest

from analyze_snapshot_mpg_strategy import available_mpg_rows, score_completed_decisions


class AvailableMpgRowsTests(unittest.TestCase):
    def test_filters_completed_games_missing_from_snapshot(self) -> None:
        mpg_rows = [
            {"home_team": "Mexico", "away_team": "South Africa"},
            {"home_team": "United States", "away_team": "Paraguay"},
            {"home_team": "Canada", "away_team": "Bosnia"},
        ]
        probability_rows = [
            {"home_team": "USA", "away_team": "Paraguay"},
            {"home_team": "Canada", "away_team": "Bosnia & Herzegovina"},
        ]
        exact_score_rows = [
            {"home_team": "USA", "away_team": "Paraguay"},
        ]

        self.assertEqual(
            available_mpg_rows(mpg_rows, probability_rows, exact_score_rows),
            [mpg_rows[1]],
        )


class CompletedDecisionScoringTests(unittest.TestCase):
    def test_scores_result_and_exact_bonus_from_snapshot_decision(self) -> None:
        strategy_rows = [
            {
                "home_team": "Home",
                "away_team": "Away",
                "matched_home_team": "Home",
                "matched_away_team": "Away",
                "optimal_pick": "Home",
                "optimal_exact_score": "2-1",
                "optimal_pick_points": 60.0,
                "optimal_expected_points": 40.0,
            },
            {
                "home_team": "Draw Home",
                "away_team": "Draw Away",
                "matched_home_team": "Draw Home",
                "matched_away_team": "Draw Away",
                "optimal_pick": "Draw",
                "optimal_exact_score": "0-0",
                "optimal_pick_points": 110.0,
                "optimal_expected_points": 35.0,
            },
        ]
        completed_rows = [
            {
                "home_team": "Home",
                "away_team": "Away",
                "home_score": "2",
                "away_score": "1",
                "final_score": "2-1",
                "actual_exact_bonus_points": "50",
            },
            {
                "home_team": "Draw Home",
                "away_team": "Draw Away",
                "home_score": "1",
                "away_score": "1",
                "final_score": "1-1",
                "actual_exact_bonus_points": "20",
            },
        ]

        scored = score_completed_decisions(strategy_rows, completed_rows)

        self.assertEqual(scored[0]["realized_points"], 110.0)
        self.assertEqual(scored[0]["realized_minus_expected_points"], 70.0)
        self.assertEqual(scored[1]["realized_points"], 110.0)
        self.assertFalse(scored[1]["exact_score_correct"])

    def test_leaves_unresolved_decision_blank(self) -> None:
        strategy_rows = [
            {
                "home_team": "Home",
                "away_team": "Away",
                "matched_home_team": "Home",
                "matched_away_team": "Away",
                "optimal_pick": "Home",
                "optimal_exact_score": "1-0",
                "optimal_pick_points": 50.0,
                "optimal_expected_points": 30.0,
            }
        ]

        scored = score_completed_decisions(strategy_rows, [])

        self.assertFalse(scored[0]["completed"])
        self.assertEqual(scored[0]["realized_points"], "")


if __name__ == "__main__":
    unittest.main()
