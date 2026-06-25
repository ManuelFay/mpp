#!/usr/bin/env python3
"""Plot 1X2 outcome calibration for all Europe 2025-26 workbook sheets."""

from __future__ import annotations

import argparse
import csv
import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "data/analysis/calibration/historical/all-euro-data-2025-2026.xlsx"
DEFAULT_OUT_DIR = ROOT / "data/analysis/calibration/historical"
DEFAULT_OUTPUT_PREFIX = "all_euro_2025"

XML_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def write_csv(path: str | Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def column_index(cell_ref: str) -> int:
    letters = "".join(char for char in cell_ref if char.isalpha())
    index = 0
    for char in letters:
        index = index * 26 + ord(char.upper()) - ord("A") + 1
    return index - 1


def read_shared_strings(zip_file: ZipFile) -> list[str]:
    root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("main:si", XML_NS):
        text_parts = [text.text or "" for text in item.findall(".//main:t", XML_NS)]
        values.append("".join(text_parts))
    return values


def workbook_sheets(zip_file: ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(zip_file.read("xl/workbook.xml"))
    relationships = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
    id_to_target = {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in relationships
    }
    result: list[tuple[str, str]] = []
    for sheet in workbook.find("main:sheets", XML_NS):
        name = sheet.attrib["name"]
        relationship_id = sheet.attrib[
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        ]
        target = id_to_target[relationship_id]
        path = target[1:] if target.startswith("/") else f"xl/{target}"
        result.append((name, path))
    return result


def cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value_node = cell.find("main:v", XML_NS)
    if value_node is not None and value_node.text is not None:
        if cell_type == "s":
            return shared_strings[int(value_node.text)]
        return value_node.text
    if cell_type == "inlineStr":
        text_node = cell.find(".//main:t", XML_NS)
        return text_node.text if text_node is not None and text_node.text is not None else ""
    return ""


def iter_sheet_rows(
    zip_file: ZipFile,
    sheet_path: str,
    shared_strings: list[str],
) -> list[dict[str, str]]:
    header: list[str] | None = None
    rows: list[dict[str, str]] = []
    with zip_file.open(sheet_path) as sheet_file:
        for _, element in ET.iterparse(sheet_file, events=("end",)):
            if not element.tag.endswith("}row"):
                continue
            values: list[str] = []
            for cell in element:
                if not cell.tag.endswith("}c"):
                    continue
                index = column_index(cell.attrib.get("r", "A1"))
                while len(values) <= index:
                    values.append("")
                values[index] = cell_value(cell, shared_strings)
            if header is None:
                header = values
            elif any(values):
                row = {
                    column: values[index] if index < len(values) else ""
                    for index, column in enumerate(header)
                }
                rows.append(row)
            element.clear()
    return rows


def read_workbook(path: str | Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with ZipFile(path) as zip_file:
        shared_strings = read_shared_strings(zip_file)
        for sheet_name, sheet_path in workbook_sheets(zip_file):
            for row in iter_sheet_rows(zip_file, sheet_path, shared_strings):
                row["sheet"] = sheet_name
                rows.append(row)
    return rows


def parse_float(value: str) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def proportional_probabilities(
    home_odds: float,
    draw_odds: float,
    away_odds: float,
) -> dict[str, float]:
    raw = {
        "H": 1.0 / home_odds,
        "D": 1.0 / draw_odds,
        "A": 1.0 / away_odds,
    }
    total = sum(raw.values())
    return {outcome: probability / total for outcome, probability in raw.items()}


def power_probabilities(home_odds: float, draw_odds: float, away_odds: float) -> dict[str, float]:
    raw = {
        "H": 1.0 / home_odds,
        "D": 1.0 / draw_odds,
        "A": 1.0 / away_odds,
    }

    def total_at(exponent: float) -> float:
        return sum(probability**exponent for probability in raw.values())

    low = 0.01
    high = 10.0
    while total_at(high) > 1.0:
        high *= 2
    while total_at(low) < 1.0:
        low /= 2
    for _ in range(80):
        middle = (low + high) / 2
        if total_at(middle) > 1.0:
            low = middle
        else:
            high = middle
    exponent = (low + high) / 2
    return {outcome: probability**exponent for outcome, probability in raw.items()}


def vig_free_probabilities(
    home_odds: float,
    draw_odds: float,
    away_odds: float,
    method: str,
) -> dict[str, float]:
    if method == "proportional":
        return proportional_probabilities(home_odds, draw_odds, away_odds)
    if method == "power":
        return power_probabilities(home_odds, draw_odds, away_odds)
    raise ValueError(f"Unknown devig method: {method}")


def wilson_interval(hits: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = hits / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def odds_from_row(row: dict[str, str]) -> tuple[float, float, float, str] | None:
    for prefix, label in (("AvgC", "closing_average"), ("Avg", "opening_average")):
        odds = [
            parse_float(row.get(f"{prefix}H", "")),
            parse_float(row.get(f"{prefix}D", "")),
            parse_float(row.get(f"{prefix}A", "")),
        ]
        if all(value is not None for value in odds):
            return odds[0], odds[1], odds[2], label  # type: ignore[return-value]
    return None


def build_records(rows: list[dict[str, str]], method: str = "proportional") -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for row in rows:
        odds = odds_from_row(row)
        if odds is None or row.get("FTR") not in {"H", "D", "A"}:
            continue
        home_odds, draw_odds, away_odds, odds_source = odds
        probabilities = vig_free_probabilities(home_odds, draw_odds, away_odds, method)
        match = f"{row['HomeTeam']} vs {row['AwayTeam']}"
        for outcome, probability in probabilities.items():
            records.append(
                {
                    "division": row.get("Div", row.get("sheet", "")),
                    "sheet": row.get("sheet", ""),
                    "date": row["Date"],
                    "match": match,
                    "outcome": outcome,
                    "actual_outcome": row["FTR"],
                    "odds_source": odds_source,
                    "devig_method": method,
                    "predicted_probability": probability,
                    "hit": int(row["FTR"] == outcome),
                }
            )
    return records


def summarize_bins(records: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for index in range(10):
        low = index / 10
        high = (index + 1) / 10
        in_bin = [
            row
            for row in records
            if low <= float(row["predicted_probability"]) < high
            or (high == 1.0 and low <= float(row["predicted_probability"]) <= high)
        ]
        if not in_bin:
            continue
        n = len(in_bin)
        hits = sum(int(row["hit"]) for row in in_bin)
        observed = hits / n
        average = sum(float(row["predicted_probability"]) for row in in_bin) / n
        wilson_low, wilson_high = wilson_interval(hits, n)
        summaries.append(
            {
                "bin": f"{int(low * 100)}-{int(high * 100)}",
                "bin_low": low,
                "bin_high": high,
                "n": n,
                "hits": hits,
                "avg_predicted_probability": average,
                "observed_hit_rate": observed,
                "wilson_low": wilson_low,
                "wilson_high": wilson_high,
            }
        )
    return summaries


def plot(
    path: str | Path,
    summaries: list[dict[str, object]],
    match_count: int,
    title: str,
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpp-matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [100 * float(row["avg_predicted_probability"]) for row in summaries]
    ys = [100 * float(row["observed_hit_rate"]) for row in summaries]
    yerr = [
        [100 * (float(row["observed_hit_rate"]) - float(row["wilson_low"])) for row in summaries],
        [100 * (float(row["wilson_high"]) - float(row["observed_hit_rate"])) for row in summaries],
    ]

    fig, ax = plt.subplots(figsize=(8, 7))
    ax.plot([0, 100], [0, 100], color="#555555", linestyle="--", linewidth=1.8, label="Perfect calibration")
    ax.errorbar(
        xs,
        ys,
        yerr=yerr,
        marker="o",
        color="#1f77b4",
        linewidth=2,
        capsize=4,
        label="Observed outcome rate",
    )
    for x, y, row in zip(xs, ys, summaries):
        ax.annotate(
            f"n={row['n']}\n{row['hits']}/{row['n']}",
            xy=(x, y),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color="#333333",
        )
    ax.set_title(title)
    ax.set_xlabel("Average vig-free 1X2 probability (%)")
    ax.set_ylabel("Outcome occurred (%)")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.grid(color="#dddddd", linewidth=0.8)
    ax.legend(loc="upper left")
    fig.text(
        0.01,
        0.01,
        f"Resolved matches={match_count} | outcome rows={match_count * 3} | "
        "Avg closing odds vig-removed",
        fontsize=9,
        color="#444444",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--output-prefix", default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--title", default="All Europe 2025-26 outcome calibration")
    parser.add_argument(
        "--method",
        choices=["proportional", "power"],
        default="proportional",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    records = build_records(read_workbook(args.input), args.method)
    summaries = summarize_bins(records)
    summary_fields = [
        "bin",
        "bin_low",
        "bin_high",
        "n",
        "hits",
        "avg_predicted_probability",
        "observed_hit_rate",
        "wilson_low",
        "wilson_high",
    ]
    write_csv(
        out_dir / f"{args.output_prefix}_outcome_calibration_records.csv",
        records,
        [
            "division",
            "sheet",
            "date",
            "match",
            "outcome",
            "actual_outcome",
            "odds_source",
            "devig_method",
            "predicted_probability",
            "hit",
        ],
    )
    write_csv(out_dir / f"{args.output_prefix}_outcome_calibration.csv", summaries, summary_fields)
    plot_path = out_dir / f"{args.output_prefix}_outcome_calibration.png"
    plot(plot_path, summaries, len(records) // 3, args.title)
    print(f"Matched games: {len(records) // 3}")
    print(f"Outcome records: {len(records)}")
    print(f"Saved plot: {plot_path}")


if __name__ == "__main__":
    main()
