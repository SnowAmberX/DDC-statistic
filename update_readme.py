from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def _format_average(value: Any) -> str:
    if isinstance(value, int):
        return str(value)

    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")

    return str(value)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_underfilled_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        ddc_raw = item.get("ddc")
        if ddc_raw is None:
            continue

        ddc = str(ddc_raw).strip()
        if not ddc:
            continue
        if ddc.isdigit():
            ddc = ddc.zfill(3)

        sample_number = item.get("current_count", item.get("sample_number", item.get("count", 0)))
        normalized.append({"ddc": ddc, "sample_number": _safe_int(sample_number, 0)})

    return normalized


def _normalize_grouped_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        ddc_range_raw = item.get("ddc_range")
        if ddc_range_raw is None:
            continue

        ddc_range = str(ddc_range_raw).strip()
        if not ddc_range:
            continue

        total_records = _safe_int(item.get("total_records", item.get("count", 0)), 0)
        normalized.append({"ddc_range": ddc_range, "total_records": total_records})

    return normalized


def _build_underfilled_table(underfilled: list[dict[str, Any]]) -> str:
    lines = ["| DDC | Sample Number |", "| --- | --- |"]
    if underfilled:
        for item in underfilled:
            ddc = str(item.get("ddc", ""))
            sample_number = _safe_int(item.get("sample_number", 0), 0)
            lines.append(f"| {ddc} | {sample_number} |")
    else:
        lines.append("| None | 0 |")
    return "\n".join(lines)


def _build_grouped_table(groups: list[dict[str, Any]]) -> str:
    lines = ["| DDC Range | Total Records |", "| --- | --- |"]
    if groups:
        for item in groups:
            ddc_range = str(item.get("ddc_range", ""))
            total_records = _safe_int(item.get("total_records", 0), 0)
            lines.append(f"| {ddc_range} | {total_records} |")
    else:
        lines.append("| None | 0 |")
    return "\n".join(lines)


def build_statistics_block(stats: dict[str, Any]) -> str:
    abstract_stats = stats.get("abstract_stats", {})
    ddc_under_100 = stats.get("ddc_under_100", {})
    ddc_under_100_count = ddc_under_100.get("ddc_under_100_count", 0)

    valid_sample_total = _safe_int(
        stats.get(
            "valid_sample_total",
            abstract_stats.get("total_records", 0) if isinstance(abstract_stats, dict) else 0,
        ),
        0,
    )
    min_description_length = _safe_int(
        stats.get(
            "min_description_length",
            abstract_stats.get("min", 20) if isinstance(abstract_stats, dict) else 20,
        ),
        20,
    )
    max_description_length = _safe_int(
        stats.get(
            "max_description_length",
            abstract_stats.get("max", 1000) if isinstance(abstract_stats, dict) else 1000,
        ),
        1000,
    )
    average_description_length = _format_average(
        stats.get(
            "average_description_length",
            abstract_stats.get("mean", 0) if isinstance(abstract_stats, dict) else 0,
        )
    )

    underfilled_raw = stats.get("underfilled_ddc")
    if underfilled_raw is None and isinstance(ddc_under_100, dict):
        underfilled_raw = ddc_under_100.get("details", [])

    underfilled_ddc = _normalize_underfilled_items(underfilled_raw)

    table = _build_underfilled_table(underfilled_ddc)

    grouped_raw = stats.get("ddc_group_by_10", [])
    grouped_ddc = _normalize_grouped_items(grouped_raw)
    grouped_table = _build_grouped_table(grouped_ddc)

    return (
        "## Statistics\n\n"
        "### DDC data distribution\n\n"
        "DDC that already having 100 samples will not show details of the distribution.\n\n"
        f"**Vaild samples number in total: {valid_sample_total}**\n\n"
        f"DDC number that not satisfy the requirement of 100 samples have: {ddc_under_100_count} \n\n"
        "**DDC number that not satisfy the requirement of 100 samples:**\n"
        f"{table}\n\n"
        "**DDC grouped by 10 (000-009 to 990-999):**\n"
        f"{grouped_table}\n\n"
        "### DDC data quality\n\n"
        f"**Minimal length of description: {min_description_length}**\n\n"
        f"**Maximal length of description: {max_description_length}**\n\n"
        f"**Average length of description: {average_description_length}**\n"
    )


def replace_statistics_section(readme_content: str, statistics_block: str) -> str:
    pattern = re.compile(r"(?ms)^## Statistics\s*\n.*?(?=^##\s|\Z)")

    if pattern.search(readme_content):
        return pattern.sub(statistics_block + "\n", readme_content, count=1)

    base = readme_content.rstrip() + "\n\n"
    return base + statistics_block + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Update README statistics section.")
    parser.add_argument("--stats-file", default="statistics.json", help="JSON statistics file.")
    parser.add_argument("--readme", default="README.md", help="README file to update.")
    args = parser.parse_args()

    stats_file = Path(args.stats_file)
    readme_file = Path(args.readme)

    stats = json.loads(stats_file.read_text(encoding="utf-8"))
    readme_content = readme_file.read_text(encoding="utf-8")

    new_statistics_block = build_statistics_block(stats)
    new_readme_content = replace_statistics_section(readme_content, new_statistics_block)

    if new_readme_content != readme_content:
        readme_file.write_text(new_readme_content, encoding="utf-8")
        print(f"Updated {readme_file}")
    else:
        print("README is already up to date.")


if __name__ == "__main__":
    main()