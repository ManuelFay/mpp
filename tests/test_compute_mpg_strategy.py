import unittest
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from compute_mpg_strategy import (
    OUT_FIELDS,
    SCORE_EV_FIELDS,
    bettor_share_estimates,
    canonical_score,
    load_bettor_behavior_multipliers,
    write_strategy_snapshot,
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


class StrategySnapshotTests(unittest.TestCase):
    def test_snapshot_is_timestamped_and_immutable(self) -> None:
        captured_at = datetime(2026, 6, 14, 21, 41, 36, tzinfo=UTC)
        strategy_row = {field: "" for field in OUT_FIELDS}
        score_ev_row = {field: "" for field in SCORE_EV_FIELDS}

        with TemporaryDirectory() as directory:
            paths = write_strategy_snapshot(
                [strategy_row],
                [score_ev_row],
                directory,
                {"probability_file": "probabilities.csv"},
                captured_at,
            )

            self.assertIn("2026/06", paths[0].as_posix())
            self.assertTrue(paths[0].name.endswith("20260614T214136Z.csv"))
            metadata = json.loads(paths[2].read_text(encoding="utf-8"))
            self.assertEqual(metadata["inputs"]["probability_file"], "probabilities.csv")

            with self.assertRaises(FileExistsError):
                write_strategy_snapshot(
                    [strategy_row],
                    [score_ev_row],
                    directory,
                    {"probability_file": "probabilities.csv"},
                    captured_at,
                )


if __name__ == "__main__":
    unittest.main()
