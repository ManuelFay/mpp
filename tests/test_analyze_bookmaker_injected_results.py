import unittest
import sys
from pathlib import Path

SIMULATION_DIR = Path(__file__).resolve().parents[1] / "data/analysis/strategy_simulations"
sys.path.insert(0, str(SIMULATION_DIR))
from analyze_bookmaker_injected_results import (
    random_player_expected_points,
    random_player_realized_points,
    score_completed_picks,
    score_random_player_games,
    simulate_random_player_resolved_totals,
    simulate_random_player_totals,
)


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
                "game_stage": "elimination",
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

    def test_scores_selected_bettor_share_transfer_variant(self) -> None:
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
                "match": "Home vs Away",
                "rank": "1",
                "score": "0-1",
                "outcome": "away",
                "outcome_probability": "0.3",
                "exact_score_probability": "0.1",
                "conditional_bettor_share": "0.1",
                "conditional_share_sigma": "0.01",
                "nominal_bonus_points": "50",
                "total_ev": "32",
                "bettor_share_transfer": "transfer",
                "game_stage": "elimination",
            },
        ]
        completed = [
            {
                "commence_time": "2026-06-14T01:00:00Z",
                "home_team": "Home",
                "away_team": "Away",
                "home_score": "0",
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
        ]

        default_scored = score_completed_picks(predictions, completed, mpg)
        transfer_scored = score_completed_picks(
            predictions,
            completed,
            mpg,
            bettor_share_transfer="transfer",
        )

        self.assertEqual(default_scored[0].selected_score, "1-0")
        self.assertEqual(default_scored[0].realized_points, 0)
        self.assertEqual(transfer_scored[0].selected_score, "0-1")
        self.assertEqual(transfer_scored[0].realized_points, 170)

    def test_transfer_variant_uses_no_transfer_rows_for_non_elimination(self) -> None:
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
                "bettor_share_transfer": "no_transfer",
                "game_stage": "group",
            },
            {
                "logged_at_utc": "2026-06-14T00:00:00+00:00",
                "match": "Home vs Away",
                "rank": "1",
                "score": "0-1",
                "outcome": "away",
                "outcome_probability": "0.3",
                "exact_score_probability": "0.1",
                "conditional_bettor_share": "0.1",
                "conditional_share_sigma": "0.01",
                "nominal_bonus_points": "50",
                "total_ev": "32",
                "bettor_share_transfer": "transfer",
                "game_stage": "group",
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
            bettor_share_transfer="transfer",
        )

        self.assertEqual(scored[0].selected_score, "1-0")
        self.assertEqual(scored[0].realized_points, 100)

    def test_actual_bonus_override_uses_real_mpg_payout(self) -> None:
        predictions = [
            {
                "logged_at_utc": "2026-06-27T00:00:00+00:00",
                "match": "Uruguay vs Spain",
                "rank": "1",
                "score": "0-1",
                "outcome": "away",
                "outcome_probability": "0.6",
                "exact_score_probability": "0.1",
                "conditional_bettor_share": "0.1",
                "conditional_share_sigma": "0.01",
                "nominal_bonus_points": "50",
                "total_ev": "43",
            },
        ]
        completed = [
            {
                "commence_time": "2026-06-27T01:00:00Z",
                "home_team": "Uruguay",
                "away_team": "Spain",
                "home_score": "0",
                "away_score": "1",
            },
        ]
        mpg = [
            {
                "home_team": "Uruguay",
                "away_team": "Spain",
                "home_odds": "143",
                "draw_odds": "112",
                "away_odds": "57",
            },
        ]

        scored = score_completed_picks(predictions, completed, mpg)

        self.assertEqual(scored[0].exact_bonus_points, 70)
        self.assertEqual(scored[0].realized_points, 127)

    def test_random_player_uses_bettor_share_selection_weights(self) -> None:
        predictions = [
            {
                "logged_at_utc": "2026-06-14T00:00:00+00:00",
                "submission_id": "sub-1",
                "match": "Home vs Away",
                "conditional_share_sigma": "0",
                "rank": "1",
                "score": "1-0",
                "outcome": "home",
                "outcome_probability": "0.5",
                "exact_score_probability": "0.1",
                "conditional_bettor_share": "0.25",
                "nominal_bonus_points": "30",
                "total_ev": "28",
            },
            {
                "logged_at_utc": "2026-06-14T00:00:00+00:00",
                "submission_id": "sub-1",
                "match": "Home vs Away",
                "conditional_share_sigma": "0",
                "rank": "2",
                "score": "0-1",
                "outcome": "away",
                "outcome_probability": "0.3",
                "exact_score_probability": "0.2",
                "conditional_bettor_share": "1",
                "nominal_bonus_points": "20",
                "total_ev": "40",
            },
        ]
        odds = [
            {
                "logged_at_utc": "2026-06-14T00:00:00+00:00",
                "submission_id": "sub-1",
                "match": "Home vs Away",
                "home_team": "Home",
                "away_team": "Away",
                "home_goals": "1",
                "away_goals": "0",
                "score": "1-0",
                "odds_decimal": "10",
                "bet_percentage": "75",
            },
            {
                "logged_at_utc": "2026-06-14T00:00:00+00:00",
                "submission_id": "sub-1",
                "match": "Home vs Away",
                "home_team": "Home",
                "away_team": "Away",
                "home_goals": "0",
                "away_goals": "1",
                "score": "0-1",
                "odds_decimal": "5",
                "bet_percentage": "25",
            },
            {
                "logged_at_utc": "2026-06-14T00:00:00+00:00",
                "submission_id": "sub-1",
                "match": "Home vs Away",
                "home_team": "Home",
                "away_team": "Away",
                "home_goals": "",
                "away_goals": "",
                "score": "Other",
                "odds_decimal": "20",
                "bet_percentage": "5",
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

        games = score_random_player_games(predictions, odds, completed, mpg)

        self.assertEqual(len(games), 1)
        self.assertAlmostEqual(games[0].candidates[0].selection_probability, 0.75)
        self.assertAlmostEqual(games[0].candidates[1].selection_probability, 0.25)
        self.assertAlmostEqual(random_player_realized_points(games), 52.5)
        self.assertGreater(random_player_expected_points(games), 0)
        totals = simulate_random_player_totals(games, rollouts=20, seed=1)
        self.assertEqual(len(totals), 20)
        resolved_totals = simulate_random_player_resolved_totals(
            games,
            players=100,
            seed=1,
        )
        self.assertEqual(len(resolved_totals), 100)
        self.assertTrue(set(resolved_totals).issubset({0.0, 70.0}))


if __name__ == "__main__":
    unittest.main()
