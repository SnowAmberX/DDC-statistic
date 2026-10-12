"""
用途：验证数据合并流程能够规范化标准列名并保留 remark 列。
核心职责：
- 验证标准列名不受大小写和首尾空格影响。
- 验证历史三列输入会补充空 remark。
- 验证新四列输入会保留已有 remark。
- 验证重复记录会优先保留非空 remark。
- 验证旧数据补齐三位、新 DL1/DL2 来源编码和跨层级过滤去重。
"""

from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MERGE_DIR = PROJECT_ROOT / "data" / "data_merge"
TEST_TEMP_DIR = PROJECT_ROOT / ".codex-tmp"
if str(MERGE_DIR) not in sys.path:
    sys.path.insert(0, str(MERGE_DIR))

try:
    import fasttext  # noqa: F401
except ModuleNotFoundError:
    sys.modules["fasttext"] = types.ModuleType("fasttext")

import merge_dedup_all3cols as merge_script


class ProjectTemporaryDirectoryTest(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_DIR.mkdir(exist_ok=True)


class LoadAndNormalizeRemarkTest(ProjectTemporaryDirectoryTest):
    def test_normalizes_canonical_headers_ignoring_case_and_whitespace(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as temp_dir:
            pd.DataFrame(
                [
                    {
                        " dDc ": "888",
                        " TITLE ": "Moralia",
                        " Description ": "A complete collection of classical essays.",
                        " REMARK ": "ai-generated",
                    }
                ]
            ).to_csv(Path(temp_dir) / "mixed_headers.csv", index=False)

            with patch.object(merge_script, "BASE_DIR", temp_dir):
                result = merge_script.load_and_normalize(
                    {"path": "mixed_headers.csv"}
                )

        self.assertEqual(
            result.to_dict(orient="records"),
            [
                {
                    "DDC": "888",
                    "Title": "Moralia",
                    "description": "A complete collection of classical essays.",
                    "remark": "ai-generated",
                }
            ],
        )

    def test_fills_missing_remark_with_blank(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as temp_dir:
            pd.DataFrame(
                [{"DDC": "123", "Title": "Legacy", "description": "Legacy description"}]
            ).to_csv(Path(temp_dir) / "legacy.csv", index=False)

            with patch.object(merge_script, "BASE_DIR", temp_dir):
                result = merge_script.load_and_normalize({"path": "legacy.csv"})

        self.assertEqual(
            result.to_dict(orient="records"),
            [
                {
                    "DDC": "123",
                    "Title": "Legacy",
                    "description": "Legacy description",
                    "remark": "",
                }
            ],
        )

    def test_csv_checkout_line_endings_do_not_change_multiline_descriptions(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as temp_dir:
            Path(temp_dir, "multiline.csv").write_bytes(
                b'DDC,Title,description\r\n8,Book,"First line.\r\nSecond line."\r\n'
            )
            with patch.object(merge_script, "BASE_DIR", temp_dir):
                result = merge_script.load_and_normalize({"path": "multiline.csv"})

        self.assertEqual(result.loc[0, "description"], "First line.\nSecond line.")

    def test_preserves_code_widths_and_leading_zeros_from_csv_and_excel(self) -> None:
        codes = ["0", "00", "000", "8", "08", "008", "80", "080", "800", 7, 80]
        for extension, source_column in (("csv", "mds_code"), ("xlsx", "DDC-L3")):
            with self.subTest(extension=extension):
                with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as temp_dir:
                    path = Path(temp_dir) / f"codes.{extension}"
                    source = pd.DataFrame(
                        {
                            source_column: codes,
                            "Title": ["Book"] * len(codes),
                            "description": ["Description"] * len(codes),
                        }
                    )
                    if extension == "csv":
                        source.to_csv(path, index=False)
                    else:
                        source.to_excel(path, index=False)

                    with patch.object(merge_script, "BASE_DIR", temp_dir):
                        result = merge_script.load_and_normalize(
                            {"path": path.name, "rename": {source_column: "DDC"}}
                        )

                self.assertEqual(result["DDC"].tolist(), [str(code) for code in codes])


class MergeRemarkDeduplicationTest(ProjectTemporaryDirectoryTest):
    def test_duplicate_record_prefers_nonempty_remark(self) -> None:
        description = (
            "one two three four five six seven eight nine ten eleven twelve "
            "thirteen fourteen fifteen sixteen"
        )

        with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as temp_dir:
            merge_dir = Path(temp_dir) / "data_merge"
            merge_dir.mkdir()
            pd.DataFrame(
                [{"DDC": "123", "Title": "Legacy", "description": description}]
            ).to_csv(merge_dir / "legacy.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "DDC": "123",
                        "Title": "Generated",
                        "description": description,
                        "remark": "ai-generated",
                    }
                ]
            ).to_csv(merge_dir / "generated.csv", index=False)

            with (
                patch.object(merge_script, "BASE_DIR", str(merge_dir)),
                patch.object(
                    merge_script,
                    "FILES",
                    [{"path": "legacy.csv"}, {"path": "generated.csv"}],
                ),
                patch.object(merge_script, "get_auto_book_description_files", return_value=[]),
                patch.object(merge_script, "ENABLE_ENGLISH_ONLY_FILTER", False),
                patch.object(merge_script, "UNDEFINED_DDC", []),
            ):
                merge_script.main()

            for output_name in (
                "merged_dedup_all3cols.xlsx",
                "merged_dedup_all3cols_clean.xlsx",
            ):
                result = pd.read_excel(Path(temp_dir) / output_name, dtype=str).fillna("")
                with self.subTest(output_name=output_name):
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result.loc[0, "remark"], "ai-generated")

    def test_conflicting_nonempty_remarks_keep_first_input_value(self) -> None:
        target_description = (
            "target one two three four five six seven eight nine ten eleven twelve "
            "thirteen fourteen fifteen"
        )
        filler_description = (
            "filler one two three four five six seven eight nine ten eleven twelve "
            "thirteen fourteen fifteen"
        )
        rows = []
        for index in range(200):
            if index % 2 == 0:
                rows.append(
                    {
                        "DDC": "200",
                        "Title": "Filler",
                        "description": filler_description,
                        "remark": f"filler-{index}",
                    }
                )
            else:
                rows.append(
                    {
                        "DDC": "100",
                        "Title": "Target",
                        "description": target_description,
                        "remark": "first" if index == 1 else f"later-{index}",
                    }
                )

        with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as temp_dir:
            merge_dir = Path(temp_dir) / "data_merge"
            merge_dir.mkdir()
            pd.DataFrame(rows).to_csv(merge_dir / "conflicts.csv", index=False)

            with (
                patch.object(merge_script, "BASE_DIR", str(merge_dir)),
                patch.object(merge_script, "FILES", [{"path": "conflicts.csv"}]),
                patch.object(merge_script, "get_auto_book_description_files", return_value=[]),
                patch.object(merge_script, "ENABLE_ENGLISH_ONLY_FILTER", False),
                patch.object(merge_script, "UNDEFINED_DDC", []),
            ):
                merge_script.main()

            result = pd.read_excel(Path(temp_dir) / "merged_dedup_all3cols.xlsx", dtype=str)
            target_row = result.loc[result["DDC"] == "100"].iloc[0]

        self.assertEqual(target_row["remark"], "first")

    def test_distinct_records_keep_their_input_order(self) -> None:
        first_description = (
            "first one two three four five six seven eight nine ten eleven twelve "
            "thirteen fourteen fifteen"
        )
        second_description = (
            "second one two three four five six seven eight nine ten eleven twelve "
            "thirteen fourteen fifteen"
        )

        with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as temp_dir:
            merge_dir = Path(temp_dir) / "data_merge"
            merge_dir.mkdir()
            pd.DataFrame(
                [
                    {
                        "DDC": "123",
                        "Title": "First",
                        "description": first_description,
                        "remark": "",
                    },
                    {
                        "DDC": "123",
                        "Title": "Second",
                        "description": second_description,
                        "remark": "ai-generated",
                    },
                ]
            ).to_csv(merge_dir / "ordered.csv", index=False)

            with (
                patch.object(merge_script, "BASE_DIR", str(merge_dir)),
                patch.object(merge_script, "FILES", [{"path": "ordered.csv"}]),
                patch.object(merge_script, "get_auto_book_description_files", return_value=[]),
                patch.object(merge_script, "ENABLE_ENGLISH_ONLY_FILTER", False),
                patch.object(merge_script, "UNDEFINED_DDC", []),
            ):
                merge_script.main()

            result = pd.read_excel(Path(temp_dir) / "merged_dedup_all3cols.xlsx", dtype=str)

        self.assertEqual(
            result["description"].tolist(),
            [first_description, second_description],
        )

    def test_preserves_existing_remark(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as temp_dir:
            pd.DataFrame(
                [
                    {
                        "DDC": "456",
                        "Title": "Generated",
                        "description": "Generated description",
                        "remark": "ai-generated",
                    }
                ]
            ).to_csv(Path(temp_dir) / "generated.csv", index=False)

            with patch.object(merge_script, "BASE_DIR", temp_dir):
                result = merge_script.load_and_normalize({"path": "generated.csv"})

        self.assertEqual(
            result.to_dict(orient="records"),
            [
                {
                    "DDC": "456",
                    "Title": "Generated",
                    "description": "Generated description",
                    "remark": "ai-generated",
                }
            ],
        )


class MergeDdcCodeTest(ProjectTemporaryDirectoryTest):
    def merge_codes(self, codes, undefined_codes):
        description = (
            "one two three four five six seven eight nine ten eleven twelve "
            "thirteen fourteen fifteen sixteen"
        )
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as temp_dir:
            merge_dir = Path(temp_dir) / "data_merge"
            merge_dir.mkdir()
            pd.DataFrame(
                {
                    "DDC": codes,
                    "Title": [f"Book {index}" for index in range(len(codes))],
                    "description": [description] * len(codes),
                    "remark": [""] * (len(codes) - 1) + ["ai-generated"],
                }
            ).to_csv(merge_dir / "codes.csv", index=False)

            with (
                patch.object(merge_script, "BASE_DIR", str(merge_dir)),
                patch.object(merge_script, "FILES", [{"path": "codes.csv"}]),
                patch.object(merge_script, "get_auto_book_description_files", return_value=[]),
                patch.object(merge_script, "ENABLE_ENGLISH_ONLY_FILTER", False),
                patch.object(merge_script, "UNDEFINED_DDC", undefined_codes),
            ):
                merge_script.main()

            return {
                output_name: pd.read_excel(Path(temp_dir) / output_name, dtype=str).fillna("")
                for output_name in (
                    "merged_dedup_all3cols.xlsx",
                    "merged_dedup_all3cols_clean.xlsx",
                )
            }

    def test_legacy_codes_are_padded_before_deduplication_and_numeric_sort(self) -> None:
        outputs = self.merge_codes(
            ["800", "80", "080", "008", "8", "08", "000", "0", "00", "10", "2", "8"],
            [],
        )
        for output_name, result in outputs.items():
            with self.subTest(output_name=output_name):
                self.assertEqual(
                    result["DDC"].tolist(),
                    ["000", "002", "008", "010", "080", "800"],
                )
                self.assertEqual(result.columns.tolist(), merge_script.TARGET_COLS)
                row = result.loc[result["DDC"] == "008"].iloc[0]
                self.assertEqual(row["Title"], "Book 3")
                self.assertEqual(row["remark"], "ai-generated")

    def test_legacy_undefined_codes_are_filtered_after_padding(self) -> None:
        outputs = self.merge_codes(
            ["8", "08", "008", "008.2", "8.0", "80", "080", "800", "123.45",
             "1000", "-8", "bad", "", None],
            ["008", "080"],
        )
        for output_name, result in outputs.items():
            with self.subTest(output_name=output_name):
                self.assertEqual(result["DDC"].tolist(), ["123", "800"])

    def test_level_workbooks_keep_hierarchy_while_legacy_sources_are_padded(self) -> None:
        description = (
            "one two three four five six seven eight nine ten eleven twelve "
            "thirteen fourteen fifteen sixteen"
        )
        sources = [
            ("Lib_Dataset_Level3_26Nov25_final.xlsx", "DDC-L3", ["0", "8", "80", "800"], "DL3"),
            ("Lib_Dataset_Level1_30Nov25_final.xlsx", "DDC-L1", ["000", "100", "800"], "DL1"),
            ("Lib_Dataset_Level2_27Nov25_final.xlsx", "DDC-L2", ["000", "010", "080", 80, "800"], "DL2"),
        ]
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as temp_dir:
            merge_dir = Path(temp_dir) / "data_merge"
            merge_dir.mkdir()
            for filename, column, codes, level in sources:
                pd.DataFrame(
                    {
                        column: codes,
                        "Title": [level] * len(codes),
                        "Abstract": [description] * len(codes),
                    }
                ).to_excel(merge_dir / filename, index=False)

            # 自动发现的历史 CSV 同样应补齐三位，且不影响低层级的同摘要记录。
            pd.DataFrame(
                [{"DDC": "1", "Title": "Legacy CSV", "description": description}]
            ).to_csv(merge_dir / "book_descriptions_all.csv", index=False)
            source_names = {source[0] for source in sources}
            with (
                patch.object(merge_script, "BASE_DIR", str(merge_dir)),
                patch.object(merge_script, "FILES", [
                    cfg for cfg in merge_script.FILES if cfg["path"] in source_names
                ]),
                patch.object(merge_script, "ENABLE_ENGLISH_ONLY_FILTER", False),
                patch.object(merge_script, "UNDEFINED_DDC", ["008"]),
            ):
                merge_script.main()

            for output_name in (
                "merged_dedup_all3cols.xlsx",
                "merged_dedup_all3cols_clean.xlsx",
            ):
                result = pd.read_excel(Path(temp_dir) / output_name, dtype=str)
                with self.subTest(output_name=output_name):
                    self.assertEqual(result.columns.tolist(), ["DDC", "Title", "description", "remark"])
                    self.assertEqual(len(result), 11)
                    self.assertEqual(set(result.loc[result["Title"] == "DL1", "DDC"]), {"0", "1", "8"})
                    self.assertEqual(set(result.loc[result["Title"] == "DL2", "DDC"]), {"00", "01", "08", "80"})
                    self.assertEqual(set(result.loc[result["Title"] == "DL3", "DDC"]), {"000", "080", "800"})
                    self.assertEqual(result.loc[result["Title"] == "Legacy CSV", "DDC"].tolist(), ["001"])


if __name__ == "__main__":
    unittest.main()
