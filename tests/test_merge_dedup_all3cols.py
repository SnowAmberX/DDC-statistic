"""
用途：验证数据合并流程能够兼容并保留 remark 列。
核心职责：
- 验证历史三列输入会补充空 remark。
- 验证新四列输入会保留已有 remark。
- 验证重复记录会优先保留非空 remark。
"""

from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import pandas as pd


MERGE_DIR = Path(__file__).resolve().parents[1] / "data" / "data_merge"
if str(MERGE_DIR) not in sys.path:
    sys.path.insert(0, str(MERGE_DIR))

try:
    import fasttext  # noqa: F401
except ModuleNotFoundError:
    sys.modules["fasttext"] = types.ModuleType("fasttext")

import merge_dedup_all3cols as merge_script


class LoadAndNormalizeRemarkTest(unittest.TestCase):
    def test_fills_missing_remark_with_blank(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pd.DataFrame(
                [{"DDC": "123", "Title": "Legacy", "description": "Legacy description"}]
            ).to_csv(Path(temp_dir) / "legacy.csv", index=False)

            with patch.object(merge_script, "BASE_DIR", temp_dir):
                result = merge_script.load_and_normalize({"path": "legacy.csv"})

        self.assertEqual(
            result.to_dict(orient="records"),
            [
                {
                    "DDC": 123,
                    "Title": "Legacy",
                    "description": "Legacy description",
                    "remark": "",
                }
            ],
        )


class MergeRemarkDeduplicationTest(unittest.TestCase):
    def test_duplicate_record_prefers_nonempty_remark(self) -> None:
        description = (
            "one two three four five six seven eight nine ten eleven twelve "
            "thirteen fourteen fifteen sixteen"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
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
                result = pd.read_excel(Path(temp_dir) / output_name).fillna("")
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

        with tempfile.TemporaryDirectory() as temp_dir:
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

            result = pd.read_excel(Path(temp_dir) / "merged_dedup_all3cols.xlsx")
            target_row = result.loc[result["DDC"] == 100].iloc[0]

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

        with tempfile.TemporaryDirectory() as temp_dir:
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

            result = pd.read_excel(Path(temp_dir) / "merged_dedup_all3cols.xlsx")

        self.assertEqual(
            result["description"].tolist(),
            [first_description, second_description],
        )

    def test_preserves_existing_remark(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
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
                    "DDC": 456,
                    "Title": "Generated",
                    "description": "Generated description",
                    "remark": "ai-generated",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
