import unittest
import sys
from pathlib import Path

SIMULATION_DIR = Path(__file__).resolve().parents[1] / "data/analysis/strategy_simulations"
sys.path.insert(0, str(SIMULATION_DIR))
from analyze_bookmaker_injected_results import score_completed_picks


class ScoreCompletedBookmakerPicksTests(unittest.TestCase):
    def test_scores_result_only_and_exact_hits(self) -> None:
        predictions = [
            {
                "logged_at_utc": "2026-06-14T00:00:00+00:00",
                "match": "Home vs Away",
                "rank": "1",
                "score": "1-0",
                "outcome": "home",
                "outcome_probability": "0.5",
                "exact_score_probability": "0.1",
                "conditional_bettor_share": "0.1",
                "conditional_share_sigma": "0.01",
                "nominal_bonus_points": "50",
                "total_ev": "35",
            },
            {
                "logged_at_utc": "2026-06-14T00:00:00+00:00",
                "match": "Other vs Visitor",
                "rank": "1",
                "score": "2-1",
                "outcome": "home",
                "outcome_probability": "0.6",
                "exact_score_probability": "0.2",
                "conditional_bettor_share": "0.2",
                "conditional_share_sigma": "0.01",
                "nominal_bonus_points": "30",
                "total_ev": "40",
            },
        ]
        completed = [
            {
                "commence_time": "2026-06-14T01:00:00Z",
                "home_team": "Home",
                "away_team": "Away",
                "home_score": "2",
                "away_score": "0",
            },
            {
                "commence_time": "2026-06-14T02:00:00Z",
                "home_team": "Other",
                "away_team": "Visitor",
                "home_score": "2",
                "away_score": "1",
            },
        ]
        mpg = [
            {
                "home_team": "Home",
                "away_team": "Away",
                "home_odds": "50",
                "draw_odds": "100",
                "away_odds": "120",
            },
            {
                "home_team": "Other",
                "away_team": "Visitor",
                "home_odds": "60",
                "draw_odds": "100",
                "away_odds": "110",
            },
        ]

        scored = score_completed_picks(predictions, completed, mpg)

        self.assertEqual(scored[0].realized_points, 50)
        self.assertFalse(scored[0].exact_score_correct)
        self.assertEqual(scored[1].realized_points, 90)
        self.assertTrue(scored[1].exact_score_correct)

    def test_can_ignore_picks_logged_after_kickoff(self) -> None:
        predictions = [
            {
                "logged_at_utc": "2026-06-14T01:00:00+00:00",
                "match": "Home vs Away",
                "rank": "1",
                "score": "1-0",
                "outcome": "home",
                "outcome_probability": "0.5",
                "exact_score_probability": "0.1",
                "conditional_bettor_share": "0.1",
                "conditional_share_sigma": "0.01",
                "nominal_bonus_points": "50",
                "total_ev": "35",
            },
        ]
        completed = [
            {
                "commence_time": "2026-06-14T01:00:00Z",
                "home_team": "Home",
                "away_team": "Away",
                "home_score": "1",
                "away_score": "0",
            },
        ]
        mpg = [
            {
                "home_team": "Home",
                "away_team": "Away",
                "home_odds": "50",
                "draw_odds": "100",
                "away_odds": "120",
            },
        ]

        scored = score_completed_picks(
            predictions,
            completed,
            mpg,
            require_pre_kickoff=True,
        )

        self.assertEqual(scored, [])

    def test_cutoff_excludes_later_predictions(self) -> None:
        predictions = [
            {
                "logged_at_utc": "2026-06-14T00:00:00+00:00",
                "match": "Home vs Away",
                "rank": "1",
                "score": "1-0",
                "outcome": "home",
                "outcome_probability": "0.5",
                "exact_score_probability": "0.1",
                "conditional_bettor_share": "0.1",
                "conditional_share_sigma": "0.01",
                "nominal_bonus_points": "50",
                "total_ev": "35",
            },
            {
                "logged_at_utc": "2026-06-14T00:30:00+00:00",
                "match": "Home vs Away",
                "rank": "1",
                "score": "2-0",
                "outcome": "home",
                "outcome_probability": "0.5",
                "exact_score_probability": "0.1",
                "conditional_bettor_share": "0.1",
                "conditional_share_sigma": "0.01",
                "nominal_bonus_points": "50",
                "total_ev": "40",
            },
        ]
        completed = [
            {
                "commence_time": "2026-06-14T01:00:00Z",
                "home_team": "Home",
                "away_team": "Away",
                "home_score": "2",
                "away_score": "0",
            },
        ]
        mpg = [
            {
                "home_team": "Home",
                "away_team": "Away",
                "home_odds": "50",
                "draw_odds": "100",
                "away_odds": "120",
            },
        ]

        scored = score_completed_picks(
            predictions,
            completed,
            mpg,
            prediction_cutoff_utc="2026-06-14T00:30:00+00:00",
        )

        self.assertEqual(len(scored), 1)
        self.assertEqual(scored[0].selected_score, "1-0")


if __name__ == "__main__":
    unittest.main()
