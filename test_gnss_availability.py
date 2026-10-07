import unittest
from datetime import timedelta

from gnss_availability import build_rows, date_arg, merge, parse_rinex
from availability_images import daily_cells
from availability_config import folder_identity, header_station, selection_matches, selected_row
from pathlib import Path
from unittest.mock import patch


def header(content, label):
    return content.ljust(60) + label + '\n'


def fixture(seconds=(0, 15, 45), scale='UTC'):
    text = header('     3.05           OBSERVATION DATA    M', 'RINEX VERSION / TYPE')
    text += header('G    3 C1C L1C S1C', 'SYS / # / OBS TYPES')
    text += header('    15.000', 'INTERVAL')
    text += header('  2026     9     1     0     0    0.0000000'.ljust(48) + scale, 'TIME OF FIRST OBS')
    text += header('    18', 'LEAP SECONDS')
    text += header('', 'END OF HEADER')
    for sec in seconds:
        text += f'> 2026 09 01 00 00 {sec:10.7f}  0  1\n'
        text += 'G01' + f'{20000000:14.3f}  ' + f'{100000000:14.3f}1 ' + f'{45:14.3f}  ' + '\n'
    return text.encode()


class AvailabilityTests(unittest.TestCase):
    def test_header_name_and_all_filters(self):
        data = header('     2.11           OBSERVATION DATA    M', 'RINEX VERSION / TYPE')
        data += header('GRTM', 'MARKER NAME') + header('', 'END OF HEADER')
        self.assertEqual(header_station(data.encode()), 'GRTM')
        self.assertEqual(header_station(data.replace('GRTM', '-UNKNOWN-').encode()), '')
        self.assertTrue(selection_matches('ALL', 'DEMPO'))
        self.assertTrue(selection_matches(['DEMPO', 'RINJANI'], 'rinjani'))
        row = {'station': 'DEMPO/GRTM', 'station_name': 'GRTM', 'folder_station': 'GTMD', 'volcano': 'DEMPO'}
        self.assertTrue(selected_row(row, {'station_filter': ['GTMD']}))
        self.assertFalse(selected_row(row, {'volcanoes': ['KRAKATAU']}))

    def test_multiple_volcanoes_same_station_do_not_merge(self):
        from gnss_availability import analyze
        import tempfile
        with tempfile.TemporaryDirectory(prefix='gnss_test_') as temp:
            root = Path(temp)
            for volcano in ['DEMPO', 'KRAKATAU']:
                folder = root / volcano / 'FOLDER' / '2026' / '09' / '01'
                folder.mkdir(parents=True)
                (folder / 'test.obs').write_bytes(fixture())
            with patch('gnss_availability.header_station', return_value='SAME'), patch('builtins.print'):
                stations, reports = analyze(root, {}, 'utc')
            self.assertEqual(set(stations), {'DEMPO/SAME', 'KRAKATAU/SAME'})
            self.assertEqual(len(reports), 2)
            rows = build_rows(stations, {'stations': {'DEMPO/SAME': {'interval_seconds': 30}}}, date_arg('2026-09-01'), date_arg('2026-09-01T01:00:00'))
            self.assertEqual({r['interval_seconds'] for r in rows if r['volcano'] == 'DEMPO'}, {30})
            self.assertEqual({r['interval_seconds'] for r in rows if r['volcano'] == 'KRAKATAU'}, {15})

    def test_folder_layout(self):
        self.assertEqual(folder_identity(Path('DEMPO/CDEM/2026/10/01/test.obs'), Path('rawdata')), ('DEMPO', 'CDEM'))
        self.assertEqual(folder_identity(Path('CDEM/2026/10/01/test.obs'), Path('rawdata/DEMPO')), ('DEMPO', 'CDEM'))

    def test_config_period_filters_and_cli_all_override(self):
        from gnss_availability import main
        import tempfile
        import json
        import sys
        with tempfile.TemporaryDirectory(prefix='gnss_config_test_') as temp:
            folder = Path(temp)
            report = folder / 'data.json'
            rows = [{'station': 'DEMPO/TEST', 'station_name': 'TEST', 'volcano': 'DEMPO', 'folder_station': 'TEST', 'hour_utc': t} for t in ['2026-09-01T00:00:00Z', '2026-10-01T00:00:00Z']]
            rows.append(dict(rows[-1], volcano='RINJANI', station='RINJANI/TEST'))
            report.write_text(json.dumps(rows), encoding='utf-8')
            config = folder / 'config.json'
            config.write_text(json.dumps({'volcanoes': ['DEMPO'], 'period': {'start': '2026-10-01', 'end': '2026-10-02'}, 'split_by_volcano': False, 'image': {'mode': 'daily'}}), encoding='utf-8')
            argv = ['script', '--config', str(config), '--from-report', str(report)]
            with patch.object(sys, 'argv', argv), patch('availability_images.write_images', return_value=[]) as export:
                main()
            self.assertEqual(len(export.call_args.args[1]), 1)
            self.assertEqual(export.call_args.args[0], (folder / 'output').resolve())
            with patch.object(sys, 'argv', argv + ['--volcano', 'ALL', '--start', 'ALL', '--end', 'ALL']), patch('availability_images.write_images', return_value=[]) as export:
                main()
            self.assertEqual(len(export.call_args.args[1]), 3)

    def test_daily_weighting_and_partial_unknown(self):
        rows = [
            {'station': 'TEST', 'hour_utc': '2026-09-01T00:00:00Z', 'status': 'complete', 'expected_epochs': 120, 'availability_percent': 100},
            {'station': 'TEST', 'hour_utc': '2026-09-01T01:00:00Z', 'status': 'missing', 'expected_epochs': 240, 'availability_percent': 0},
            {'station': 'TEST', 'hour_utc': '2026-09-01T02:00:00Z', 'status': 'unknown', 'expected_epochs': 240, 'availability_percent': None},
            {'station': 'TEST', 'hour_utc': '2026-09-01T03:00:00Z', 'status': 'inactive', 'expected_epochs': None, 'availability_percent': None},
        ]
        cell = daily_cells(rows)[('TEST', '2026-09-01')]
        self.assertAlmostEqual(cell['percent'], 100 / 3)
        self.assertEqual(cell['unknown_hours'], 1)
        self.assertEqual(cell['active_hours'], 3)

    def test_daily_unknown_not_zero(self):
        rows = [{'station': 'TEST', 'hour_utc': '2026-09-01T00:00:00Z', 'status': 'unknown', 'expected_epochs': 240, 'availability_percent': None}]
        cell = daily_cells(rows)[('TEST', '2026-09-01')]
        self.assertIsNone(cell['percent'])
        self.assertEqual(cell['unknown_hours'], 1)

    def test_observations_and_gap_and_duplicates(self):
        obs, interval, warnings = parse_rinex(fixture())
        self.assertEqual(len(obs), 3)
        self.assertEqual(interval, 15)
        self.assertFalse(warnings)
        first = next(iter(obs.values()))
        self.assertEqual(first['snr'][('G01', 'S1C')], 45)
        self.assertIn(('G01', 'L1C'), first['lli'])
        merge(obs, parse_rinex(fixture())[0])
        self.assertEqual(len(obs), 3)
        start = date_arg('2026-09-01')
        state = {'epochs': obs, 'intervals': [15], 'files': [], 'spans': []}
        row = build_rows({'TEST': state}, {}, start, start + timedelta(minutes=1))[0]
        self.assertEqual(row['epochs'], 3)
        self.assertEqual(row['expected_epochs'], 4)
        self.assertEqual(row['availability_percent'], 75)
        self.assertEqual(row['longest_gap_seconds'], 15)
        self.assertEqual(row['gap_count'], 1)

    def test_time_scale_override_and_header_conversion(self):
        data = fixture((30,), 'GPS')
        utc, _, warnings = parse_rinex(data, 'utc')
        converted, _, _ = parse_rinex(data, 'header')
        self.assertTrue(warnings)
        self.assertEqual((next(iter(utc)) - next(iter(converted))).total_seconds(), 18)

    def test_unreadable_is_unknown_not_missing(self):
        start = date_arg('2026-09-01')
        state = {'epochs': {}, 'intervals': [], 'spans': [], 'files': [{'status': 'unknown', 'path': 'bad.T02', 'nominal_start': '2026-09-01T00:00:00Z', 'nominal_end': '2026-09-01T01:00:00Z'}]}
        rows = build_rows({'TEST': state}, {'interval_seconds': 15}, start, start + timedelta(hours=2))
        self.assertEqual(rows[0]['status'], 'unknown')
        self.assertEqual(rows[1]['status'], 'missing')

    def test_empty_numeric_observations_are_not_available(self):
        data = fixture((0,)).decode()
        data = data[:data.index('\nG01') + 1] + 'G01' + ' ' * 48 + '\n'
        with self.assertRaisesRegex(ValueError, 'Tidak ada epoch'):
            parse_rinex(data.encode())

    def test_rinex2_satellite_continuation_and_blank_fields(self):
        text = header('     2.11           OBSERVATION DATA    G', 'RINEX VERSION / TYPE')
        text += header('     2    C1    S1', '# / TYPES OF OBSERV')
        text += header('', 'END OF HEADER')
        sats = [f'G{n:02}' for n in range(1, 14)]
        text += ' 26 09 01 00 00  0.0000000  0 13' + ''.join(sats[:12]) + '\n'
        text += ' ' * 32 + sats[-1] + '\n'
        for sat in sats:
            text += f'{20000000:14.3f}  ' + (' ' * 16 if sat == 'G13' else f'{42:14.3f}  ') + '\n'
        obs, _, _ = parse_rinex(text.encode())
        first = next(iter(obs.values()))
        self.assertEqual(len(first['satellites']), 13)
        self.assertEqual(len(first['snr']), 12)

    def test_inactive_hours_excluded(self):
        start = date_arg('2026-09-01')
        state = {'epochs': {}, 'intervals': [15], 'spans': [], 'files': []}
        rows = build_rows({'TEST': state}, {'stations': {'TEST': {'active_start': '2026-09-01T01:00:00Z'}}}, start, start + timedelta(hours=2))
        self.assertEqual(rows[0]['status'], 'inactive')
        self.assertIsNone(rows[0]['expected_epochs'])
        self.assertEqual(rows[1]['expected_epochs'], 240)


if __name__ == '__main__':
    unittest.main()
