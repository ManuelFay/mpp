import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from compute_mpg_strategy import (
    bettor_share_estimates,
    canonical_score,
    load_bettor_behavior_multipliers,
)


def exact_row_with_home_scores() -> dict[str, str]:
    row = {
        f"score_{home_goals}_{away_goals}_probability": "0"
        for home_goals in range(5)
        for away_goals in range(5)
    }
    row.update(
        {
            "score_1_0_probability": "0.2",
            "score_2_0_probability": "0.1",
            "other_home_win_probability": "0.2",
            "other_draw_probability": "0",
            "other_away_win_probability": "0",
        }
    )
    return row


class BettorBehaviorTests(unittest.TestCase):
    def test_canonical_score_is_orientation_neutral(self) -> None:
        self.assertEqual(canonical_score(2, 1), "2-1")
        self.assertEqual(canonical_score(1, 2), "2-1")
        self.assertEqual(canonical_score(1, 1), "1-1")

    def test_adjusted_shares_include_other_mass_in_normalization(self) -> None:
        shares = bettor_share_estimates(
            exact_row_with_home_scores(),
            "home",
            {"1-0": 0.5, "2-0": 2.0},
        )

        self.assertAlmostEqual(shares["1-0"]["model_conditional_probability"], 0.4)
        self.assertAlmostEqual(shares["2-0"]["model_conditional_probability"], 0.2)
        self.assertAlmostEqual(shares["1-0"]["conditional_probability"], 0.2)
        self.assertAlmostEqual(shares["2-0"]["conditional_probability"], 0.4)
        # The remaining 0.4 belongs to the unmodified Other bucket.
        self.assertAlmostEqual(
            sum(value["conditional_probability"] for value in shares.values()),
            0.6,
        )

    def test_unspecified_scores_default_to_neutral_multiplier(self) -> None:
        shares = bettor_share_estimates(exact_row_with_home_scores(), "home", {})

        self.assertAlmostEqual(
            shares["1-0"]["conditional_probability"],
            shares["1-0"]["model_conditional_probability"],
        )

    def test_multiplier_file_rejects_non_positive_values(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "multipliers.csv"
            path.write_text(
                "canonical_score,multiplier\n2-1,0\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_bettor_behavior_multipliers(path)


if __name__ == "__main__":
    unittest.main()
