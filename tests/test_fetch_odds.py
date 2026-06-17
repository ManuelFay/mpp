import csv
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from fetch_odds import CSV_FIELDS, write_csv


class OddsSnapshotTests(unittest.TestCase):
    def test_immutable_write_refuses_existing_snapshot(self) -> None:
        row = {field: "" for field in CSV_FIELDS}

        with TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.csv"
            write_csv([row], path, overwrite=False)

            with self.assertRaises(FileExistsError):
                write_csv([row], path, overwrite=False)

            with path.open(newline="", encoding="utf-8") as file:
                self.assertEqual(len(list(csv.DictReader(file))), 1)


if __name__ == "__main__":
    unittest.main()
