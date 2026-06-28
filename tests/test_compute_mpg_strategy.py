import unittest
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from compute_mpg_strategy import (
    OUT_FIELDS,
    SCORE_EV_FIELDS,
    adjusted_exact_score_row,
    bettor_share_estimates,
    canonical_score,
    comparison_row,
    load_bettor_behavior_multipliers,
    outcome_probabilities_for_strategy,
    select_game_window,
    top_bets_by_game,
    unresolved_mpg_rows,
    write_top_bets_xlsx,
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


class EliminationAdjustmentTests(unittest.TestCase):
    def test_elimination_outcome_probabilities_shift_draw_mass_to_non_draws(self) -> None:
        probabilities, transition = outcome_probabilities_for_strategy(
            {
                "game_stage": "elimination",
                "home_probability": "0.5",
                "draw_probability": "0.3",
                "away_probability": "0.2",
            }
        )

        self.assertAlmostEqual(probabilities["home"], 0.5214285714285715)
        self.assertAlmostEqual(probabilities["draw"], 0.27)
        self.assertAlmostEqual(probabilities["away"], 0.20857142857142857)
        self.assertAlmostEqual(transition["draw_retention_factor"], 0.9)

    def test_elimination_exact_score_moves_draw_mass_up_one_goal(self) -> None:
        row = {
            f"score_{home_goals}_{away_goals}_probability": "0"
            for home_goals in range(5)
            for away_goals in range(5)
        }
        row.update(
            {
                "score_1_1_probability": "0.12",
                "other_home_win_probability": "0",
                "other_draw_probability": "0",
                "other_away_win_probability": "0",
            }
        )

        adjusted = adjusted_exact_score_row(
            row,
            {
                "draw_retention_factor": 0.9,
                "home_share": 0.7142857142857143,
                "away_share": 0.2857142857142857,
            },
        )

        self.assertAlmostEqual(float(adjusted["score_1_1_probability"]), 0.108)
        self.assertAlmostEqual(float(adjusted["score_2_1_probability"]), 0.008571428571428568)
        self.assertAlmostEqual(float(adjusted["score_1_2_probability"]), 0.003428571428571427)
        self.assertAlmostEqual(float(adjusted["score_1_0_probability"]), 0.0)

    def test_elimination_exact_score_moves_out_of_grid_draws_to_other(self) -> None:
        row = {
            f"score_{home_goals}_{away_goals}_probability": "0"
            for home_goals in range(5)
            for away_goals in range(5)
        }
        row.update(
            {
                "score_4_4_probability": "0.10",
                "other_home_win_probability": "0",
                "other_draw_probability": "0",
                "other_away_win_probability": "0",
            }
        )

        adjusted = adjusted_exact_score_row(
            row,
            {
                "draw_retention_factor": 0.9,
                "home_share": 0.75,
                "away_share": 0.25,
            },
        )

        self.assertAlmostEqual(float(adjusted["score_4_4_probability"]), 0.09)
        self.assertAlmostEqual(float(adjusted["other_home_win_probability"]), 0.0075)
        self.assertAlmostEqual(float(adjusted["other_away_win_probability"]), 0.0025)
        self.assertAlmostEqual(float(adjusted["other_draw_probability"]), 0.0)


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


class StrategyWindowTests(unittest.TestCase):
    def test_select_game_window_returns_day_2_games(self) -> None:
        rows = [
            {
                "date": f"2026-06-{(index // 4) + 11:02d}",
                "time": f"{(index % 4) * 3:02d}:00",
                "home_team": f"Home {index:02d}",
                "away_team": f"Away {index:02d}",
            }
            for index in reversed(range(60))
        ]

        selected = select_game_window(rows, offset=24, limit=24)

        self.assertEqual(len(selected), 24)
        self.assertEqual(selected[0]["home_team"], "Home 24")
        self.assertEqual(selected[-1]["home_team"], "Home 47")

    def test_unresolved_mpg_rows_excludes_completed_games(self) -> None:
        mpg_rows = [
            {"home_team": "Mexico", "away_team": "South Africa"},
            {"home_team": "Bosnia", "away_team": "Qatar"},
            {"home_team": "Curacao", "away_team": "Ivory Coast"},
        ]
        completed_rows = [
            {"home_team": "Mexico", "away_team": "South Africa"},
            {"home_team": "Curaçao", "away_team": "Ivory Coast"},
        ]

        unresolved = unresolved_mpg_rows(
            mpg_rows,
            completed_rows,
            now=datetime(2026, 6, 28, tzinfo=UTC),
        )

        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["home_team"], "Bosnia")

    def test_unresolved_mpg_rows_keeps_pre_kickoff_completed_file_rows(self) -> None:
        mpg_rows = [
            {"home_team": "Jordan", "away_team": "Argentina"},
            {"home_team": "Algeria", "away_team": "Austria"},
        ]
        completed_rows = [
            {
                "home_team": "Jordan",
                "away_team": "Argentina",
                "commence_time": "2026-06-28T02:00:00Z",
            },
            {
                "home_team": "Algeria",
                "away_team": "Austria",
                "commence_time": "2026-06-28T02:00:00Z",
            },
        ]

        unresolved = unresolved_mpg_rows(
            mpg_rows,
            completed_rows,
            now=datetime(2026, 6, 28, 1, 59, tzinfo=UTC),
        )

        self.assertEqual(
            [(row["home_team"], row["away_team"]) for row in unresolved],
            [
                ("Jordan", "Argentina"),
                ("Algeria", "Austria"),
            ],
        )

    def test_unresolved_mpg_rows_excludes_at_kickoff(self) -> None:
        mpg_rows = [{"home_team": "Jordan", "away_team": "Argentina"}]
        completed_rows = [
            {
                "home_team": "Jordan",
                "away_team": "Argentina",
                "commence_time": "2026-06-28T02:00:00Z",
            }
        ]

        unresolved = unresolved_mpg_rows(
            mpg_rows,
            completed_rows,
            now=datetime(2026, 6, 28, 2, 0, tzinfo=UTC),
        )

        self.assertEqual(unresolved, [])

    def test_comparison_row_totals_expected_and_resolved_points(self) -> None:
        strategy_rows = [
            {
                "matched_home_team": "Mexico",
                "matched_away_team": "South Africa",
                "optimal_expected_points": 42.5,
            },
            {
                "matched_home_team": "Canada",
                "matched_away_team": "Bosnia & Herzegovina",
                "optimal_expected_points": 50.0,
            },
        ]
        completed_rows = [
            {
                "home_team": "Mexico",
                "away_team": "South Africa",
                "total_points": "79",
            }
        ]

        row = comparison_row(
            "day_1",
            strategy_rows,
            completed_rows,
            offset=0,
            limit=24,
            now=datetime(2026, 6, 28, tzinfo=UTC),
        )

        self.assertEqual(row["games"], 2)
        self.assertEqual(row["resolved_games"], 1)
        self.assertAlmostEqual(float(row["expected_points"]), 92.5)
        self.assertAlmostEqual(float(row["resolved_points"]), 79.0)
        self.assertAlmostEqual(float(row["points_vs_expectancy"]), -13.5)

    def test_comparison_row_ignores_pre_kickoff_completed_file_rows(self) -> None:
        strategy_rows = [
            {
                "matched_home_team": "Jordan",
                "matched_away_team": "Argentina",
                "optimal_expected_points": 32.5,
            }
        ]
        completed_rows = [
            {
                "home_team": "Jordan",
                "away_team": "Argentina",
                "commence_time": "2026-06-28T02:00:00Z",
                "total_points": "82",
            }
        ]

        row = comparison_row(
            "round_3",
            strategy_rows,
            completed_rows,
            offset=0,
            limit=24,
            now=datetime(2026, 6, 28, 1, 59, tzinfo=UTC),
        )

        self.assertEqual(row["resolved_games"], 0)
        self.assertEqual(row["resolved_points"], "")

    def test_top_bets_by_game_returns_five_rows_per_game(self) -> None:
        rows = []
        for game_index in range(2):
            for score_index in range(7):
                rows.append(
                    {
                        "date": "2026-06-18",
                        "time": f"{18 + game_index:02d}:00",
                        "home_team": f"Home {game_index}",
                        "away_team": f"Away {game_index}",
                        "game_stage": "elimination",
                        "outcome_label": "Home",
                        "score": f"{score_index}-0",
                        "outcome_probability": 0.5,
                        "outcome_points": 60,
                        "base_expected_points": 30,
                        "score_probability": 0.01,
                        "score_model_conditional_probability": 0.1,
                        "score_conditional_probability": 0.1,
                        "exact_bonus_label": "Tres rare",
                        "exact_bonus_points": 50,
                        "exact_bonus_expected_points": 0.5,
                        "total_expected_points": score_index,
                    }
                )

        top_rows = top_bets_by_game(rows, top_n=5)

        self.assertEqual(len(top_rows), 10)
        self.assertEqual([row["rank"] for row in top_rows[:5]], [1, 2, 3, 4, 5])
        self.assertEqual(top_rows[0]["exact_score"], "6-0")
        self.assertEqual(top_rows[4]["exact_score"], "2-0")

    def test_write_top_bets_xlsx_creates_workbook(self) -> None:
        rows = [
            {
                "date": "2026-06-18",
                "time": "18:00",
                "home_team": "Czechia",
                "away_team": "South Africa",
                "game_stage": "elimination",
                "rank": 1,
                "outcome_pick": "South Africa",
                "exact_score": "0-2",
                "outcome_probability": 0.23,
                "outcome_points": 142,
                "base_expected_points": 33.6,
                "score_probability": 0.05,
                "score_model_conditional_probability": 0.2,
                "score_conditional_probability": 0.18,
                "exact_bonus_label": "Tres rare",
                "exact_bonus_points": 50,
                "exact_bonus_expected_points": 2.7,
                "total_expected_points": 36.3,
            }
        ]

        with TemporaryDirectory() as directory:
            path = Path(directory) / "top_bets.xlsx"
            write_top_bets_xlsx(rows, path)

            with zipfile.ZipFile(path) as workbook:
                self.assertIn("xl/workbook.xml", workbook.namelist())
                sheet = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
                self.assertIn("Round", workbook.read("xl/workbook.xml").decode("utf-8"))
                self.assertIn("total_expected_points", sheet)
                self.assertIn("South Africa", sheet)


if __name__ == "__main__":
    unittest.main()
