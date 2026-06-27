from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone, timedelta
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


def _normalize_ddc_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    for item in value:
        if item is None:
            continue

        ddc = str(item).strip()
        if not ddc:
            continue

        try:
            ddc = str(int(float(ddc))).zfill(3)
        except (ValueError, TypeError):
            pass

        normalized.append(ddc)

    return normalized


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
        try:
            ddc = str(int(float(ddc))).zfill(3)
        except (ValueError, TypeError):
            pass

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

        under_check_number_count = _safe_int(
            item.get("under_check_number_count", item.get("total_records", item.get("count", 0))),
            0,
        )
        ddc_list = _normalize_ddc_list(
            item.get("under_check_number_ddc_list", item.get("ddc_list", []))
        )
        normalized.append({
            "ddc_range": ddc_range,
            "under_check_number_count": under_check_number_count,
            "ddc_list": ddc_list,
        })

    return normalized


def _normalize_garbled_items(items: Any) -> list[dict[str, Any]]:
    """Normalize the ddc_group_by_10_garbled raw list from statistics.json."""
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

        normalized.append({
            "ddc_range": ddc_range,
            "total_count": _safe_int(item.get("total_count", 0), 0),
            "garbled_count": _safe_int(item.get("garbled_count", 0), 0),
            "clean_count": _safe_int(item.get("clean_count", 0), 0),
            "garbled_ratio": float(item.get("garbled_ratio", 0.0)),
        })

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


def _build_grouped_table(groups: list[dict[str, Any]], check_number: int) -> str:
    lines = [
        f"| DDC Range | DDC < {check_number} Count | DDC List |",
        "| --- | --- | --- |",
    ]
    if groups:
        non_zero_groups = [
            item
            for item in groups
            if _safe_int(item.get("under_check_number_count", 0), 0) > 0
        ]
        if non_zero_groups:
            for item in non_zero_groups:
                ddc_range = str(item.get("ddc_range", ""))
                under_check_number_count = _safe_int(item.get("under_check_number_count", 0), 0)
                ddc_list = item.get("ddc_list", [])
                ddc_list_display = ", ".join(ddc_list) if ddc_list else "-"
                lines.append(
                    f"| {ddc_range} | {under_check_number_count} | {ddc_list_display} |"
                )
        else:
            lines.append("| None | - | - |")
    else:
        lines.append("| None | - | - |")
    return "\n".join(lines)


def _build_garbled_table(groups: list[dict[str, Any]]) -> str:
    """Build a Markdown table for garbled text statistics by DDC range."""
    lines = [
        "| DDC Range | Total Records | Garbled Records | Garbled Ratio | Clean Records |",
        "| --- | --- | --- | --- | --- |",
    ]
    if groups:
        non_zero_groups = [
            item
            for item in groups
            if _safe_int(item.get("garbled_count", 0), 0) > 0
        ]
        if non_zero_groups:
            for item in non_zero_groups:
                ddc_range = str(item.get("ddc_range", ""))
                total_count = _safe_int(item.get("total_count", 0), 0)
                garbled_count = _safe_int(item.get("garbled_count", 0), 0)
                clean_count = _safe_int(item.get("clean_count", 0), 0)
                ratio = item.get("garbled_ratio", 0.0)
                ratio_str = f"{ratio:.2%}" if isinstance(ratio, (int, float)) else str(ratio)
                lines.append(
                    f"| {ddc_range} | {total_count} | {garbled_count} | {ratio_str} | {clean_count} |"
                )
        else:
            lines.append("| None | - | - | - | - |")
    else:
        lines.append("| None | - | - | - | - |")
    return "\n".join(lines)


def build_statistics_block(stats: dict[str, Any]) -> str:
    abstract_stats = stats.get("abstract_stats", {})
    ddc_under_check_number = stats.get("ddc_under_check_number", {})
    ddc_under_check_number_count = ddc_under_check_number.get("ddc_under_check_number_count", 0)

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

    check_number = _safe_int(stats.get("check_number", 100), 100)

    underfilled_raw = stats.get("underfilled_ddc")
    if underfilled_raw is None and isinstance(ddc_under_check_number, dict):
        underfilled_raw = ddc_under_check_number.get("details", [])

    underfilled_ddc = _normalize_underfilled_items(underfilled_raw)

    table = _build_underfilled_table(underfilled_ddc)

    grouped_raw = stats.get("ddc_group_by_10", [])
    grouped_ddc = _normalize_grouped_items(grouped_raw)
    grouped_table = _build_grouped_table(grouped_ddc, check_number)

    garbled_raw = stats.get("ddc_group_by_10_garbled", [])
    garbled_items = _normalize_garbled_items(garbled_raw)
    garbled_table = _build_garbled_table(garbled_items)

    return (
        "## Statistics\n\n"
        "### DDC data distribution\n\n"
        f"DDC that already having {check_number} samples will not show details of the distribution.\n\n"
        f"**Vaild samples number in total: {valid_sample_total}**\n\n"
        f"DDC number that not satisfy the requirement of {check_number} samples have: {ddc_under_check_number_count} \n\n"
        f"**DDC grouped by 10 (count of DDC < {check_number}):**\n"
        f"{grouped_table}\n\n"
        f"**DDC number that not satisfy the requirement of {check_number} samples:**\n"
        f"{table}\n\n"
        "### DDC data quality\n\n"
        "**Garbled text by DDC group:**\n"
        f"{garbled_table}\n\n"
        f"**Minimal length of description: {min_description_length}**\n\n"
        f"**Maximal length of description: {max_description_length}**\n\n"
        f"**Average length of description: {average_description_length}**\n"
    )


def replace_update_timestamp(readme_content: str) -> str:
    """Insert or update the 'Last updated' timestamp line at the top of README."""
    tz_utc8 = timezone(timedelta(hours=8))
    now_str = datetime.now(tz_utc8).strftime("%Y-%m-%d %H:%M:%S")
    timestamp_line = f"> **Last updated: {now_str} (UTC+8)**\n"

    # Match an existing timestamp line
    pattern = re.compile(r"^> \*\*Last updated:.*\*\*\n?", re.MULTILINE)
    if pattern.search(readme_content):
        return pattern.sub(timestamp_line, readme_content, count=1)

    # Insert after the first heading line (e.g. "# DDC Dataset Statistics")
    heading_pattern = re.compile(r"^(# .+)$", re.MULTILINE)
    match = heading_pattern.search(readme_content)
    if match:
        insert_pos = match.end()
        return readme_content[:insert_pos] + "\n" + timestamp_line + "\n" + readme_content[insert_pos:].lstrip()

    # Fallback: prepend
    return timestamp_line + "\n" + readme_content


def replace_statistics_section(readme_content: str, statistics_block: str) -> str:
    pattern = re.compile(r"(?ms)^## Statistics\s*\n.*?(?=^##\s|\Z)")

    if pattern.search(readme_content):
        return pattern.sub(statistics_block + "\n", readme_content, count=1)

    base = readme_content.rstrip() + "\n\n"
    return base + statistics_block + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Update README statistics section.")
    parser.add_argument("--stats-file", default="/data/statistics.json", help="JSON statistics file.")
    parser.add_argument("--readme", default="README.md", help="README file to update.")
    args = parser.parse_args()

    stats_file = Path(args.stats_file)
    readme_file = Path(args.readme)

    stats = json.loads(stats_file.read_text(encoding="utf-8"))
    original_content = readme_file.read_text(encoding="utf-8")
    readme_content = original_content

    # 1) Update the timestamp at the top
    readme_content = replace_update_timestamp(readme_content)

    # 2) Update the statistics section
    new_statistics_block = build_statistics_block(stats)
    readme_content = replace_statistics_section(readme_content, new_statistics_block)

    if readme_content != original_content:
        readme_file.write_text(readme_content, encoding="utf-8")
        print(f"Updated {readme_file}")
    else:
        print("README is already up to date.")


if __name__ == "__main__":
    main()