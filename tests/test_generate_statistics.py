import contextlib
import io
import json
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]
STATISTICS_SCRIPT = PROJECT_DIR / 'generate_statistics.py'


class MixedLevelStatisticsTest(unittest.TestCase):
    def run_statistics(self, raw_rows, clean_rows):
        temporary_root = PROJECT_DIR / '.codex-tmp'
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='statistics-test-', dir=temporary_root) as temporary_dir:
            fixture_dir = Path(temporary_dir)
            data_dir = fixture_dir / 'data'
            data_dir.mkdir()
            script_path = fixture_dir / 'generate_statistics.py'
            shutil.copyfile(STATISTICS_SCRIPT, script_path)
            pd.DataFrame(raw_rows).to_excel(data_dir / 'merged_dedup_all3cols.xlsx', index=False)
            pd.DataFrame(clean_rows).to_excel(data_dir / 'merged_dedup_all3cols_clean.xlsx', index=False)

            with contextlib.redirect_stdout(io.StringIO()):
                namespace = runpy.run_path(str(script_path), run_name='__main__')

            statistics = json.loads((data_dir / 'statistics.json').read_text(encoding='utf-8'))
        return statistics, namespace

    def make_row(self, ddc, title=None, description='one two three', remark=''):
        return {
            'DDC': ddc,
            'Title': title or f'Book {ddc}',
            'description': description,
            'remark': remark,
        }

    def test_preserves_code_width_and_limits_class_reports_to_dl3(self):
        raw_rows = [
            self.make_row('0', description='short'),
            self.make_row('00'),
            self.make_row('000'),
            self.make_row('8'),
            self.make_row('08'),
            self.make_row('008'),
            self.make_row('80', title='Garbled lower level \ufffd', remark='ai-generated'),
            self.make_row('080', remark=' AI-Generated '),
            self.make_row('800'),
            self.make_row('080', title='Garbled DL3 \ufffd'),
        ]
        raw_rows.extend(self.make_row('80', title=f'Lower level {index}', remark='ai-generated')
                        for index in range(50))
        clean_rows = [row for row in raw_rows if '\ufffd' not in row['Title']]

        statistics, namespace = self.run_statistics(raw_rows, clean_rows)

        self.assertEqual(set(namespace['df_unclean']['DDC']),
                         {'0', '00', '000', '8', '08', '80', '080', '800'})
        self.assertEqual(namespace['ddc_counts']['DDC'].tolist(), ['000', '080', '800'])
        self.assertEqual(statistics['abstract_stats']['total_records'], len(clean_rows) - 1)
        self.assertEqual(statistics['abstract_stats']['min'], 1)
        self.assertEqual(namespace['total_garbled'], 2)

        class_stats = statistics['ddc_under_check_number']
        self.assertEqual(class_stats['total_ddc_classes'], 3)
        self.assertEqual(class_stats['ddc_over_check_number_count'], 0)
        details = {item['ddc']: item['current_count'] for item in class_stats['details']}
        self.assertEqual(details['000'], 1)
        self.assertEqual(details['080'], 1)
        self.assertEqual(details['800'], 1)
        self.assertNotIn('008', details)
        for code in ('0', '00', '8', '08', '80'):
            self.assertNotIn(code, details)

        groups = {item['ddc_range']: item for item in statistics['ddc_group_by_10_garbled']}
        self.assertEqual(groups['000-007']['total_count'], 1)
        self.assertEqual(groups['080-089']['total_count'], 2)
        self.assertEqual(groups['080-089']['clean_count'], 1)
        self.assertEqual(groups['080-089']['garbled_count'], 1)
        self.assertEqual(groups['080-089']['ai_count'], 1)
        self.assertEqual(groups['080-089']['ai_ratio'], 0.5)
        self.assertEqual(groups['800-809']['total_count'], 1)

    def test_lower_levels_only_leave_dl3_class_reports_empty(self):
        rows = [self.make_row(code) for code in ('0', '00', '8', '08', '80')]

        statistics, namespace = self.run_statistics(rows, rows)

        self.assertEqual(namespace['df']['DDC'].tolist(), ['0', '00', '8', '08', '80'])
        self.assertTrue(namespace['ddc_counts'].empty)
        self.assertEqual(statistics['abstract_stats']['total_records'], len(rows))
        class_stats = statistics['ddc_under_check_number']
        self.assertEqual(class_stats['total_ddc_classes'], 0)
        self.assertEqual(class_stats['ddc_over_check_number_count'], 0)
        self.assertTrue(all(item['current_count'] == 0 for item in class_stats['details']))
        details = {item['ddc']: item['current_count'] for item in class_stats['details']}
        self.assertEqual(details['080'], 0)
        self.assertEqual(details['800'], 0)
        self.assertTrue(all(item['total_count'] == 0
                            for item in statistics['ddc_group_by_10_garbled']))


if __name__ == '__main__':
    unittest.main()
