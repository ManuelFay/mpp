import unittest
import sys
from pathlib import Path

import numpy as np

SIMULATION_DIR = Path(__file__).resolve().parents[1] / "data/analysis/strategy_simulations"
sys.path.insert(0, str(SIMULATION_DIR))
from simulate_mpg_strategy import Game, run_rollouts


class CompletedGameResolutionTests(unittest.TestCase):
    def test_completed_game_uses_true_result_and_recorded_bonus(self) -> None:
        game = Game(
            event_id="completed",
            label="Home vs Away",
            result_probabilities=np.array([0.0, 0.0, 1.0]),
            population_pick_probabilities=np.array([1.0, 0.0, 0.0]),
            points=np.array([49.0, 125.0, 148.0]),
            actual_score_probabilities=(
                np.array([1.0]),
                np.array([1.0]),
                np.array([1.0]),
            ),
            population_score_probabilities=(
                np.array([1.0]),
                np.array([1.0]),
                np.array([1.0]),
            ),
            score_bonus_points=(
                np.array([100.0]),
                np.array([100.0]),
                np.array([100.0]),
            ),
            optimal_outcome=0,
            optimal_score_index=0,
            optimal_bonus_points=30.0,
            actual_outcome=0,
            actual_score_index=0,
            actual_exact_bonus_points=20.0,
        )

        population, optimal = run_rollouts([game], rollouts=5, seed=1)

        np.testing.assert_array_equal(population[:, 0], np.full(5, 69.0))
        np.testing.assert_array_equal(optimal[:, 0], np.full(5, 69.0))


if __name__ == "__main__":
    unittest.main()
