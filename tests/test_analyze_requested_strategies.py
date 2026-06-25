import csv
import sys
import tempfile
import unittest
from pathlib import Path

SIMULATION_DIR = Path(__file__).resolve().parents[1] / "data/analysis/strategy_simulations"
sys.path.insert(0, str(SIMULATION_DIR))
import analyze_requested_strategies as strategies


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class MatchingStrategyFileTests(unittest.TestCase):
    def test_falls_back_to_snapshot_covering_completed_games(self) -> None:
        completed = [
            {
                "home_team": "Mexico",
                "away_team": "South Africa",
                "final_score": "2-0",
            },
            {
                "home_team": "Canada",
                "away_team": "Bosnia & Herzegovina",
                "final_score": "1-1",
            },
        ]
        stale_score = [
            {
                "matched_home_team": "Czech Republic",
                "matched_away_team": "South Africa",
                "score": "0-0",
            }
        ]
        stale_optimal = [
            {
                "matched_home_team": "Czech Republic",
                "matched_away_team": "South Africa",
                "optimal_exact_score": "0-2",
            }
        ]
        snapshot_score = [
            {
                "matched_home_team": home,
                "matched_away_team": away,
                "score": score,
            }
            for home, away, scores in [
                ("Mexico", "South Africa", ["0-0", "1-1", "1-0", "0-1"]),
                ("Canada", "Bosnia & Herzegovina", ["0-0", "1-1", "1-0", "0-1", "2-1"]),
            ]
            for score in scores
        ]
        snapshot_optimal = [
            {
                "matched_home_team": "Mexico",
                "matched_away_team": "South Africa",
                "optimal_exact_score": "1-0",
            },
            {
                "matched_home_team": "Canada",
                "matched_away_team": "Bosnia & Herzegovina",
                "optimal_exact_score": "2-1",
            },
        ]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stale_score_path = root / "mpg_score_expected_values.csv"
            stale_optimal_path = root / "mpg_optimal_strategy.csv"
            snapshot_score_path = (
                root / "data/mpg/strategy_snapshots/2026/06/"
                "mpg_score_expected_values_20260616T094426Z.csv"
            )
            snapshot_optimal_path = (
                root / "data/mpg/strategy_snapshots/2026/06/"
                "mpg_optimal_strategy_20260616T094426Z.csv"
            )
            write_csv(stale_score_path, stale_score)
            write_csv(stale_optimal_path, stale_optimal)
            write_csv(snapshot_score_path, snapshot_score)
            write_csv(snapshot_optimal_path, snapshot_optimal)

            original_snapshot_dir = strategies.DEFAULT_SNAPSHOT_DIR
            strategies.DEFAULT_SNAPSHOT_DIR = str(root / "data/mpg/strategy_snapshots")
            try:
                score_rows, optimal_rows, score_path, optimal_path, used_snapshot = (
                    strategies.load_matching_strategy_files(
                        completed,
                        stale_score_path,
                        stale_optimal_path,
                        allow_snapshot_fallback=True,
                    )
                )
            finally:
                strategies.DEFAULT_SNAPSHOT_DIR = original_snapshot_dir

        self.assertTrue(used_snapshot)
        self.assertEqual(score_path, snapshot_score_path)
        self.assertEqual(optimal_path, snapshot_optimal_path)
        self.assertTrue(
            strategies.files_cover_completed_games(completed, score_rows, optimal_rows)
        )


if __name__ == "__main__":
    unittest.main()
