import unittest

from odds_pipeline.processing import normalize_implied_probabilities


class DevigMethodTests(unittest.TestCase):
    def test_proportional_matches_old_normalization(self) -> None:
        probabilities = normalize_implied_probabilities(
            {"home": 0.5, "draw": 0.3, "away": 0.25},
            "proportional",
        )

        self.assertAlmostEqual(probabilities["home"], 0.5 / 1.05)
        self.assertAlmostEqual(probabilities["draw"], 0.3 / 1.05)
        self.assertAlmostEqual(probabilities["away"], 0.25 / 1.05)

    def test_power_probabilities_sum_to_one_and_raise_favorite(self) -> None:
        proportional = normalize_implied_probabilities(
            {"home": 0.5, "draw": 0.3, "away": 0.25},
            "proportional",
        )
        power = normalize_implied_probabilities(
            {"home": 0.5, "draw": 0.3, "away": 0.25},
            "power",
        )

        self.assertAlmostEqual(sum(power.values()), 1.0)
        self.assertGreater(power["home"], proportional["home"])
        self.assertLess(power["away"], proportional["away"])

    def test_unknown_method_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_implied_probabilities({"home": 0.5, "away": 0.55}, "unknown")


if __name__ == "__main__":
    unittest.main()
