import unittest

import update_readme


class GarbledAndAiStatisticsTableTest(unittest.TestCase):
    def test_builds_garbled_and_ai_table(self) -> None:
        groups = update_readme._normalize_garbled_items(
            [
                {
                    "ddc_range": "100-109",
                    "total_count": 100,
                    "garbled_count": 4,
                    "clean_count": 96,
                    "garbled_ratio": 0.04,
                    "ai_count": 12,
                    "ai_ratio": 0.12,
                }
            ]
        )

        table = update_readme._build_garbled_table(groups)

        self.assertIn("| AI Records | AI Ratio |", table)
        self.assertIn("| 100-109 | 100 | 4 | 4.00% | 96 | 12 | 12.00% |", table)

    def test_uses_updated_table_title(self) -> None:
        block = update_readme.build_statistics_block(
            {
                "ddc_group_by_10_garbled": [
                    {
                        "ddc_range": "100-109",
                        "total_count": 100,
                        "garbled_count": 4,
                        "clean_count": 96,
                        "garbled_ratio": 0.04,
                        "ai_count": 12,
                        "ai_ratio": 0.12,
                    }
                ]
            }
        )

        self.assertIn("**Garbled text and AI-generated content by DDC group:**", block)

    def test_includes_ai_only_group(self) -> None:
        table = update_readme._build_garbled_table(
            [
                {
                    "ddc_range": "080-089",
                    "total_count": 100,
                    "garbled_count": 0,
                    "clean_count": 100,
                    "garbled_ratio": 0.0,
                    "ai_count": 3,
                    "ai_ratio": 0.03,
                }
            ]
        )

        self.assertIn("| 080-089 | 100 | 0 | 0.00% | 100 | 3 | 3.00% |", table)


if __name__ == "__main__":
    unittest.main()
