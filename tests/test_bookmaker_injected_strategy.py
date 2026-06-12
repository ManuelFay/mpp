import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from bookmaker_injected_strategy import (
    append_odds_log,
    append_prediction_log,
    bonus_distribution,
    normalize_team,
    rank_scores,
)


class BonusDistributionTests(unittest.TestCase):
    def test_noise_reduces_bonus_just_below_threshold(self) -> None:
        distribution = bonus_distribution(0.196, sigma=0.01)

        self.assertEqual(distribution.nominal_points, 50.0)
        self.assertLess(distribution.expected_points, 50.0)
        self.assertGreater(distribution.expected_points, 30.0)

    def test_zero_sigma_preserves_nominal_bonus(self) -> None:
        distribution = bonus_distribution(0.196, sigma=0.0)

        self.assertEqual(distribution.expected_points, 50.0)
        self.assertEqual(distribution.variance, 0.0)

    def test_noise_can_increase_expected_bonus_above_threshold(self) -> None:
        distribution = bonus_distribution(0.204, sigma=0.01)

        self.assertEqual(distribution.nominal_points, 30.0)
        self.assertGreater(distribution.expected_points, 30.0)


class RankingTests(unittest.TestCase):
    def test_team_aliases_match_probability_data(self) -> None:
        self.assertEqual(normalize_team("Bosnia"), "Bosnia & Herzegovina")
        self.assertEqual(normalize_team("Curacao"), "Curaçao")
        self.assertEqual(normalize_team("United States"), "USA")

    def test_other_odds_are_included_in_probability_normalization(self) -> None:
        rows = [
            {
                "home_goals": "1",
                "away_goals": "0",
                "score": "1-0",
                "odds_decimal": "2",
                "bet_percentage": "20",
            },
            {
                "home_goals": "0",
                "away_goals": "0",
                "score": "0-0",
                "odds_decimal": "4",
                "bet_percentage": "20",
            },
            {
                "home_goals": "",
                "away_goals": "",
                "score": "Other",
                "odds_decimal": "4",
                "bet_percentage": "60",
            },
        ]

        ranked = rank_scores(
            rows,
            {"home": 0.5, "draw": 0.3, "away": 0.2},
            {"home": 10.0, "draw": 10.0, "away": 10.0},
            "Home",
            "Away",
            sigma=0.0,
        )
        one_nil = next(row for row in ranked if row.score == "1-0")

        self.assertAlmostEqual(one_nil.score_probability, 0.5)


class LoggingTests(unittest.TestCase):
    def test_logs_raw_rows_and_prediction(self) -> None:
        input_row = {
            "match": "Home vs Away",
            "home_team": "Home",
            "away_team": "Away",
            "home_goals": "1",
            "away_goals": "0",
            "score": "1-0",
            "odds_decimal": "2",
            "bet_percentage": "100",
        }
        ranked = rank_scores(
            [input_row],
            {"home": 0.5, "draw": 0.3, "away": 0.2},
            {"home": 10.0, "draw": 10.0, "away": 10.0},
            "Home",
            "Away",
        )

        with TemporaryDirectory() as directory:
            odds_path = Path(directory) / "odds.csv"
            prediction_path = Path(directory) / "predictions.csv"
            append_odds_log(odds_path, [input_row], "2026-06-11T00:00:00+00:00", "test")
            append_prediction_log(
                prediction_path,
                "Home vs Away",
                ranked,
                "2026-06-11T00:00:00+00:00",
                "test",
                0.01,
            )

            self.assertIn("Home vs Away", odds_path.read_text(encoding="utf-8"))
            with prediction_path.open(newline="", encoding="utf-8") as file:
                prediction_rows = list(csv.DictReader(file))
            self.assertEqual(prediction_rows[0]["rank"], "1")
            self.assertEqual(prediction_rows[0]["score"], "1-0")
            self.assertEqual(prediction_rows[0]["is_best_pick"], "True")


if __name__ == "__main__":
    unittest.main()
