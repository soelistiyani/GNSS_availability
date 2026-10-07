"""GNSS observation availability, hourly UTC; Python standard library only."""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import statistics
import subprocess
import tempfile
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from availability_config import folder_identity, header_station, period_value, resolve_path, selected_row, selection_matches

UTC = timezone.utc


def number(s):
    return float(s.replace('D', 'E'))


def timestamp(parts):
    y, mo, d, h, mi = map(int, parts[:5])
    if y < 100:
        y += 2000 if y < 80 else 1900
    return datetime(y, mo, d, h, mi, tzinfo=UTC) + timedelta(seconds=number(parts[5]))


def parse_rinex(data, time_scale='utc'):
    # Some receivers write CR CR LF: normalize without removing blank observation lines.
    lines = data.decode('ascii', errors='replace').replace('\r\r\n', '\n').replace('\r\n', '\n').replace('\r', '\n').splitlines()
    if not lines or 'OBSERVATION DATA' not in lines[0]:
        raise ValueError('Bukan RINEX observation')
    version = float(lines[0][:9])
    types, system_types = [], defaultdict(list)
    interval, scale, leap = None, '', None
    i = 0
    last_system = ''
    while i < len(lines):
        line = lines[i].ljust(80)
        label = line[60:].strip()
        if label == '# / TYPES OF OBSERV':
            types.extend(line[6:60].split())
        elif label == 'SYS / # / OBS TYPES':
            last_system = line[0].strip() or last_system
            system_types[last_system].extend(line[7:60].split())
        elif label == 'INTERVAL':
            interval = number(line[:10])
        elif label == 'TIME OF FIRST OBS':
            scale = line[48:51].strip()
        elif label == 'LEAP SECONDS':
            leap = int(line[:6])
        i += 1
        if label == 'END OF HEADER':
            break
    else:
        raise ValueError('END OF HEADER tidak ditemukan')
    offset = 0
    warnings = []
    if time_scale == 'utc' and scale and scale != 'UTC':
        warnings.append(f'Header {scale}; waktu diperlakukan sebagai UTC sesuai konfigurasi')
    elif time_scale == 'header':
        if scale in ('GPS', 'GAL', 'QZS'):
            if leap is None:
                raise ValueError('Konversi ke UTC memerlukan LEAP SECONDS di header')
            offset = leap
        elif scale not in ('UTC', 'GLO'):
            raise ValueError(f'Skala waktu {scale!r} belum didukung; gunakan --time-scale utc jika data memang UTC')
    epochs = {}

    def record(t, satellites, flag):
        t -= timedelta(seconds=offset)
        active, snr, lli, signals = set(), {}, set(), set()
        for sat, obs_types, fields in satellites:
            for kind, field in zip(obs_types, fields):
                raw = field[:14].strip()
                if not raw:
                    continue
                value = number(raw)
                if not math.isfinite(value):
                    continue
                active.add(sat)
                signals.add(sat[0] + ':' + kind)
                if kind.startswith('S'):
                    snr[(sat, kind)] = value
                if kind.startswith('L') and len(field) > 14 and field[14].isdigit() and int(field[14]) & 1:
                    lli.add((sat, kind))
        if active:
            old = epochs.setdefault(t, {'satellites': set(), 'snr': {}, 'lli': set(), 'signals': set(), 'power_failure': False})
            old['satellites'].update(active)
            old['snr'].update(snr)
            old['lli'].update(lli)
            old['signals'].update(signals)
            old['power_failure'] |= flag == 1

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if version < 3:
            if len(line) < 32:
                raise ValueError(f'Epoch terpotong pada baris {i + 1}')
            flag, count = int(line[28:29]), int(line[29:32])
            i += 1
            if flag not in (0, 1, 6):
                i += count
                continue
            t = timestamp(line[:26].split())
            sat_text = line[32:68]
            for _ in range((count - 1) // 12):
                if i >= len(lines):
                    raise ValueError('Daftar satelit terpotong')
                sat_text += lines[i].ljust(68)[32:68]
                i += 1
            sats = [sat_text[j:j + 3].strip() for j in range(0, count * 3, 3)]
            records = []
            per_sat = math.ceil(len(types) / 5)
            for sat in sats:
                if i + per_sat > len(lines):
                    raise ValueError('Observasi terpotong')
                fields = []
                for _ in range(per_sat):
                    row = lines[i].ljust(80)
                    fields.extend(row[j:j + 16] for j in range(0, 80, 16))
                    i += 1
                sat = sat if sat[:1].isalpha() else 'G' + sat.zfill(2)
                records.append((sat, types, fields))
            if flag != 6:
                record(t, records, flag)
        else:
            if not line.startswith('>'):
                raise ValueError(f'Epoch RINEX 3/4 tidak valid pada baris {i + 1}')
            parts = line[1:].split()
            flag, count = int(line[31:32]), int(line[32:35])
            i += 1
            if flag not in (0, 1, 6):
                i += count
                continue
            t = timestamp(parts[:6])
            records = []
            for _ in range(count):
                if i >= len(lines):
                    raise ValueError('Observasi terpotong')
                row = lines[i]
                sat = row[:3]
                kinds = system_types.get(sat[0])
                if not kinds:
                    raise ValueError(f'Tipe observasi tidak ada untuk {sat}')
                i += 1
                payload = row[3:]
                while len(payload) < len(kinds) * 16 and i < len(lines) and lines[i].startswith('   '):
                    payload = payload.ljust(math.ceil(len(payload) / 16) * 16) + lines[i][3:]
                    i += 1
                payload = payload.ljust(len(kinds) * 16)
                records.append((sat, kinds, [payload[j:j + 16] for j in range(0, len(kinds) * 16, 16)]))
            if flag != 6:
                record(t, records, flag)
    if not epochs:
        raise ValueError('Tidak ada epoch dengan observasi numerik')
    return epochs, interval, warnings


def nominal(path):
    """Filename time is only used to place unreadable hourly files on the timeline."""
    text = str(path).replace('\\', '/')
    date = re.search(r'/(20\d{2})/(\d{2})/(\d{2})/', text)
    if date:
        day = datetime(*map(int, date.groups()), tzinfo=UTC)
    else:
        date = re.search(r'Ref\.Data\.(\d{2})/Month\.([A-Za-z]+)/Day\.(\d{2})/', text, re.I)
        if not date:
            return None, None
        months = {m: n for n, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}
        day = datetime(2000 + int(date[1]), months[date[2].lower()[:3]], int(date[3]), tzinfo=UTC)
    match = re.match(r'^[A-Za-z0-9]{4}\d{3}([a-x0])', path.name, re.I)
    if not match:
        return day, day + timedelta(days=1)
    code = match[1].lower()
    if code == '0':
        return day, day + timedelta(days=1)
    start = day + timedelta(hours=ord(code) - ord('a'))
    return start, start + timedelta(hours=1)


def kind(name):
    n = name.lower()
    if re.search(r'\.(m\d\d|mdb)$', n):
        return 'leica'
    if n.endswith(('.t01', '.t02')):
        return 'trimble'
    if n.endswith(('.obs', '.rnx')) or re.search(r'\.\d{2}o$', n):
        return 'rinex'
    return None


def executable(name, config):
    base = Path(__file__).resolve().parent
    configured = config.get('tools', {}).get(name)
    if configured:
        configured_path = Path(configured)
        if not configured_path.is_absolute():
            configured_path = base / configured_path
        return str(configured_path.resolve())
    for folder in (base / 'tools', base):
        for suffix in ('.exe', ''):
            candidate = folder / (name + suffix)
            if candidate.is_file():
                return str(candidate)
    found = shutil.which(name)
    return str(Path(found).resolve()) if found else None


def observations(data, name, config, work, nominal_start=None):
    fmt = kind(name)
    if fmt == 'rinex':
        return data, []
    source, target = work / Path(name).name, work / 'converted.obs'
    source.write_bytes(data)
    converter = config.get('converters', {}).get(fmt)
    if converter:
        argv = converter.get('argv')
        if not isinstance(argv, list) or not argv:
            raise ValueError('converter.argv harus berupa daftar argumen')
        argv = [str(a).replace('{input}', str(source)).replace('{output}', str(target)) for a in argv]
        stdout_to_file = converter.get('stdout', False)
    elif fmt == 'leica' and executable('teqc', config):
        argv, stdout_to_file = [executable('teqc', config), '-max_rx_SVs', '64', '-leica', 'mdb', str(source)], True
    elif fmt == 'trimble' and executable('runpkr00', config) and executable('teqc', config):
        result = subprocess.run([executable('runpkr00', config), '-g', '-d', str(source)], capture_output=True, timeout=config.get('converter_timeout', 180), cwd=work)
        generated = [p for p in work.iterdir() if p.suffix.lower() in ('.tgd', '.dat')]
        if result.returncode or len(generated) != 1:
            raise RuntimeError(f'runpkr00 gagal menghasilkan DAT/TGD: {result.stderr.decode(errors="replace")[-1000:]}')
        argv, stdout_to_file = [executable('teqc', config), '-max_rx_SVs', '64', str(generated[0])], True
        if nominal_start is not None:
            # DAT/TGD observation records may lack initial GPS week; do not use CPU date.
            argv[1:1] = ['-week', nominal_start.strftime('%Y:%m:%d')]
    else:
        raise RuntimeError(f'Konverter {fmt} belum tersedia; atur converters pada config.json')
    if stdout_to_file:
        with target.open('wb') as out:
            result = subprocess.run(argv, stdout=out, stderr=subprocess.PIPE, timeout=config.get('converter_timeout', 180), cwd=work)
    else:
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=config.get('converter_timeout', 180), cwd=work)
    if result.returncode:
        raise RuntimeError(f'Konverter exit {result.returncode}: {result.stderr.decode(errors="replace")[-1000:]}')
    stderr = result.stderr.decode(errors='replace')
    messages = list(dict.fromkeys(line.strip() for line in stderr.splitlines() if line.strip()))
    errors = [line for line in messages if re.search(r'\?\s*Error|rejection|fatal', line, re.I)]
    if errors:
        raise ValueError('Konverter menolak data: ' + '; '.join(errors)[:2000])
    if not target.exists() or not target.stat().st_size:
        raise ValueError('Konverter tidak menghasilkan RINEX observation: ' + '; '.join(messages[-5:])[:2000])
    return target.read_bytes(), messages[:20]


def merge(destination, incoming):
    for t, obs in incoming.items():
        if t not in destination:
            destination[t] = obs
        else:
            current = destination[t]
            for k in ('satellites', 'lli', 'signals'):
                current[k].update(obs[k])
            current['snr'].update(obs['snr'])
            current['power_failure'] |= obs['power_failure']


def iso(t):
    return t.isoformat().replace('+00:00', 'Z') if t else None


def analyze(root, config, time_scale, period_start=None, period_end=None):
    stations, reports = {}, []
    for path in sorted(root.rglob('*')):
        if not path.is_file() or (kind(path.name) is None and path.suffix.lower() != '.zip'):
            continue
        rel = path.relative_to(root)
        volcano, folder_station = folder_identity(rel, root, config.get('data_layout', 'auto'))
        if not selection_matches(config.get('volcanoes', 'ALL'), volcano):
            continue
        start, end = nominal(path)
        if start and config.get('filter_files_by_date', False) and ((period_start and end <= period_start) or (period_end and start >= period_end)):
            continue
        station_name = folder_station
        station = f'{volcano}/{station_name}'
        report = {'station': station, 'station_name': station_name, 'volcano': volcano, 'folder_station': folder_station, 'path': str(rel), 'bytes': path.stat().st_size, 'nominal_start': iso(start), 'nominal_end': iso(end), 'status': 'unknown', 'warnings': [], 'errors': [], 'observation_members': 0}
        file_epochs, file_intervals = {}, []
        try:
            if path.suffix.lower() == '.zip':
                with zipfile.ZipFile(path) as archive:
                    members = [(m.filename, archive.read(m)) for m in archive.infolist() if not m.is_dir() and kind(m.filename)]
            else:
                members = [(path.name, path.read_bytes())]
            if not members:
                raise ValueError('Tidak ditemukan file observasi yang didukung')
            for name, data in members:
                try:
                    with tempfile.TemporaryDirectory(prefix='gnss_') as temp:
                        rinex, converter_warnings = observations(data, name, config, Path(temp), start)
                        epochs, interval, warnings = parse_rinex(rinex, time_scale)
                    marker = header_station(rinex)
                    if config.get('station_name_source', 'header') == 'header' and marker:
                        if report['observation_members'] and station_name != marker:
                            raise ValueError('Anggota arsip memiliki MARKER NAME berbeda')
                        station_name = marker
                        station = f'{volcano}/{station_name}'
                    report.update(station=station, station_name=station_name, header_station=marker)
                    if marker and marker != folder_station:
                        report['warnings'].append(f'MARKER NAME {marker} berbeda dari folder {folder_station}')
                    merge(file_epochs, epochs)
                    if interval and interval > 0:
                        file_intervals.append(interval)
                    report['warnings'].extend(warnings + converter_warnings)
                    first, last = iso(min(epochs)), iso(max(epochs))
                    report['first_observation'] = min(report.get('first_observation', first), first)
                    report['last_observation'] = max(report.get('last_observation', last), last)
                    report['observation_members'] += 1
                except Exception as exc:
                    if isinstance(exc, OSError) and getattr(exc, 'winerror', None) == 14001:
                        report['errors'].append(f'{name}: Windows error 14001: konverter gagal dimulai. runpkr00 memerlukan Microsoft Visual C++ 2008 Redistributable x86 (CRT/MFC). Instal runtime yang sesuai lalu jalankan ulang.')
                    else:
                        report['errors'].append(f'{name}: {exc}')
            report['status'] = 'ok' if not report['errors'] else ('partial' if report['observation_members'] else 'unknown')
        except Exception as exc:
            report['errors'].append(str(exc))
        if not selected_row(report, config):
            continue
        reports.append(report)
        state = stations.setdefault(station, {'epochs': {}, 'intervals': [], 'files': [], 'spans': [], 'volcano': volcano, 'station_name': station_name, 'folder_station': folder_station})
        if start:
            state['spans'].append((start, end))
        state['files'].append(report)
        state['intervals'].extend(file_intervals)
        merge(state['epochs'], file_epochs)
        print(f"{station}: {rel} [{report['status']}]", flush=True)
    return stations, reports


def date_arg(value):
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def build_rows(stations, config, start=None, end=None):
    spans = [span for s in stations.values() for span in s['spans']]
    times = [t for s in stations.values() for t in s['epochs']]
    starts = [a for a, _ in spans] + times
    ends = [b for _, b in spans] + [t + timedelta(seconds=1) for t in times]
    if not starts and (start is None or end is None):
        raise ValueError('Tidak dapat menentukan rentang waktu; gunakan --start dan --end')
    start = start or min(starts).replace(minute=0, second=0, microsecond=0)
    if end is None:
        end = max(ends)
        if end.minute or end.second or end.microsecond:
            end = end.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    if end <= start:
        raise ValueError('--end harus setelah --start (end eksklusif)')
    now = datetime.now(UTC)
    rows = []
    for station, state in sorted(stations.items()):
        overrides = config.get('stations', {})
        cfg = overrides.get(station, overrides.get(state.get('station_name', station), overrides.get(state.get('folder_station', station), {})))
        interval = cfg.get('interval_seconds', config.get('interval_seconds'))
        interval_source = 'config'
        if interval is None:
            interval_source = 'header'
            interval = statistics.mode(state['intervals']) if state['intervals'] else None
        if interval is None and len(state['epochs']) > 1:
            interval_source = 'inferred'
            ts = sorted(state['epochs'])
            diffs = [round((b - a).total_seconds(), 6) for a, b in zip(ts, ts[1:]) if 0 < (b - a).total_seconds() <= 3600]
            interval = statistics.mode(diffs) if diffs else None
        if interval is not None and interval <= 0:
            raise ValueError(f'Interval {station} harus positif')
        active_start = date_arg(cfg['active_start']) if cfg.get('active_start') else start
        active_end = date_arg(cfg['active_end']) if cfg.get('active_end') else end
        buckets = defaultdict(dict)
        for t, obs in state['epochs'].items():
            buckets[t.replace(minute=0, second=0, microsecond=0)][t] = obs
        h = start.replace(minute=0, second=0, microsecond=0)
        while h < end:
            lo, hi = max(h, start, active_start), min(h + timedelta(hours=1), end, active_end, now)
            obs = {t: v for t, v in buckets[h].items() if lo <= t < hi}
            ts = sorted(obs)
            errors = [f['path'] for f in state['files'] if f['status'] != 'ok' and (not f['nominal_start'] or (date_arg(f['nominal_start']) < h + timedelta(hours=1) and date_arg(f['nominal_end']) > h))]
            duration = max(0, (hi - lo).total_seconds())
            expected = math.ceil(duration / interval - 1e-9) if interval and duration else None
            # Occupied sampling slots prevent near-duplicate/jittered epochs inflating availability.
            occupied = len({int((t - lo).total_seconds() // interval) for t in ts}) if interval else None
            pct = round(100 * min(occupied, expected) / expected, 3) if expected else None
            gaps = []
            if duration and interval:
                if ts:
                    gaps = [max(0, (ts[0] - lo).total_seconds())]
                    gaps += [max(0, (b - a).total_seconds() - interval) for a, b in zip(ts, ts[1:])]
                    gaps.append(max(0, (hi - ts[-1]).total_seconds() - interval))
                else:
                    gaps = [duration]
            # Sub-second timestamp jitter is not reported as an observation gap.
            gaps = [g for g in gaps if g > max(0.001, (interval or 0) * 0.05)]
            snr = [value for v in obs.values() for value in v['snr'].values()]
            status = 'inactive' if not duration else ('unknown' if errors else ('missing' if not ts else ('complete' if pct == 100 else 'partial')))
            if errors:
                # Unknown coverage must not be presented as a measured zero percent.
                pct = None
            rows.append({'station': station, 'hour_utc': iso(h), 'status': status, 'interval_seconds': interval, 'interval_source': interval_source, 'epochs': len(ts), 'expected_epochs': expected, 'availability_percent': pct, 'gap_count': len(gaps), 'longest_gap_seconds': round(max(gaps, default=0), 3) if interval else None, 'first_observation': iso(ts[0]) if ts else None, 'last_observation': iso(ts[-1]) if ts else None, 'satellites_mean': round(statistics.mean(len(v['satellites']) for v in obs.values()), 2) if obs else None, 'satellites_min': min((len(v['satellites']) for v in obs.values()), default=None), 'cn0_mean_dbhz': round(statistics.mean(snr), 2) if snr else None, 'loss_of_lock_flags': sum(len(v['lli']) for v in obs.values()), 'power_failure_epochs': sum(v['power_failure'] for v in obs.values()), 'signals': ', '.join(sorted({s for v in obs.values() for s in v['signals']})), 'unreadable_files': '; '.join(errors)})
            rows[-1]['source_files'] = '; '.join(f['path'] for f in state['files'] if f.get('first_observation') and date_arg(f['first_observation']) < h + timedelta(hours=1) and date_arg(f['last_observation']) >= h)
            rows[-1].update(volcano=state.get('volcano', ''), station_name=state.get('station_name', station), folder_station=state.get('folder_station', station))
            if errors:
                rows[-1]['gap_count'] = None
                rows[-1]['longest_gap_seconds'] = None
            h += timedelta(hours=1)
    return rows


def write_report(output, rows, files):
    output.mkdir(parents=True, exist_ok=True)
    for name, data in [('availability.json', rows), ('files.json', files)]:
        (output / name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    inventory = {}
    for row in rows:
        inventory[row['station']] = {k: row.get(k, '') for k in ('station', 'station_name', 'volcano', 'folder_station')}
    (output / 'stations.json').write_text(json.dumps(list(inventory.values()), indent=2, ensure_ascii=False), encoding='utf-8')
    if rows:
        with (output / 'availability.csv').open('w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    payload = json.dumps({'rows': rows, 'files': files}, ensure_ascii=False).replace('<', '\\u003c')
    page = '''<!doctype html><html lang="id"><meta charset="utf-8"><title>GNSS availability UTC</title>
<style>body{font:14px system-ui;margin:24px;background:#f7f9fb;color:#182838}h1{font-size:24px}input,select,button{padding:8px;margin:5px}table{border-collapse:collapse;background:white}th,td{padding:7px;border:1px solid #e1e6eb}th{position:sticky;top:0;background:white}.station{position:sticky;left:0;background:white;min-width:95px}.cell{min-width:21px;height:25px;padding:0;cursor:pointer}.unknown{outline:2px solid #e79026;outline-offset:-2px}.scroll{overflow:auto;max-height:60vh;margin-top:16px}pre{white-space:pre-wrap;background:white;padding:16px;border:1px solid #ddd}.legend span{display:inline-block;padding:8px;margin:4px}#summary{margin:15px 0}</style>
<h1>GNSS observation availability · UTC</h1><p>Kelengkapan epoch dan indikator observasi per jam. Klik kotak untuk detail.</p>
<label>Gunung <select id="volcano"><option value="">ALL</option></select></label>
<label>Stasiun <select id="station"><option value="">ALL</option></select></label>
<label>Mulai UTC <input type="date" id="start"></label><label>Akhir UTC (inklusif) <input type="date" id="end"></label><button id="apply">Tampilkan</button>
<div class="legend"><span style="background:#ccc">Kosong</span><span style="background:#bce4c4">Parsial</span><span style="background:#208548;color:white">Lengkap</span><span style="border:2px solid #e79026">Belum dapat dinilai</span><span style="background:#f1f3f5">Di luar periode aktif / masa depan</span></div>
<div id="summary"></div><div class="scroll"><table id="grid"></table></div><pre id="detail">Pilih kotak untuk melihat detail.</pre>
<details><summary>Hasil pemeriksaan file / konverter</summary><pre id="files"></pre></details>
<script>const data=PAYLOAD;
const el=id=>document.getElementById(id);const stations=[...new Set(data.rows.map(r=>r.station))];
const allRows=data.rows;
[...new Set(allRows.map(r=>r.volcano).filter(Boolean))].sort().forEach(v=>{let o=document.createElement('option');o.value=v;o.textContent=v;el('volcano').append(o)});
el('volcano').onchange=()=>{data.rows=allRows.filter(r=>!el('volcano').value||r.volcano===el('volcano').value);el('station').value='';draw()};
stations.forEach(s=>{let o=document.createElement('option');o.value=s;o.textContent=s;el('station').append(o)});
const dates=data.rows.map(r=>r.hour_utc.slice(0,10)).sort();el('start').value=dates[0]||'';el('end').value=dates.at(-1)||'';
function color(r){if(r.status==='inactive')return '#f1f3f5';if(!r.epochs)return '#ccc';let p=(r.availability_percent??0)/100;return `rgb(${Math.round(188-156*p)},${Math.round(228-95*p)},${Math.round(196-124*p)})`}
function draw(){let rows=data.rows.filter(r=>(!el('station').value||r.station===el('station').value)&&r.hour_utc.slice(0,10)>=el('start').value&&r.hour_utc.slice(0,10)<=el('end').value);let hours=[...new Set(rows.map(r=>r.hour_utc))].sort();let grid=el('grid');grid.replaceChildren();let head=grid.insertRow();head.append(document.createElement('th'));hours.forEach(h=>{let th=document.createElement('th');th.textContent=h.slice(5,10)+' '+h.slice(11,13);th.title=h;head.append(th)});let summaries=[];
stations.filter(s=>rows.some(r=>r.station===s)).forEach(s=>{let tr=grid.insertRow();let label=document.createElement('th');label.className='station';label.textContent=s;tr.append(label);let own=rows.filter(r=>r.station===s);let map=new Map(own.map(r=>[r.hour_utc,r]));hours.forEach(h=>{let td=tr.insertCell();let r=map.get(h);td.className='cell';if(!r)return;td.style.background=color(r);if(r.status==='unknown'||(r.epochs&&r.availability_percent===null))td.classList.add('unknown');td.title=`${s} ${h}\n${r.status} · ${r.availability_percent??'?'}%\nEpoch ${r.epochs}/${r.expected_epochs??'?'}\nGap ${r.longest_gap_seconds??'?'} detik`;td.onclick=()=>el('detail').textContent=JSON.stringify(r,null,2)});let known=own.filter(r=>!['unknown','inactive'].includes(r.status)&&r.expected_epochs);let expected=known.reduce((a,r)=>a+r.expected_epochs,0);let available=known.reduce((a,r)=>a+r.expected_epochs*r.availability_percent/100,0);summaries.push(`${s}: ${expected?(100*available/expected).toFixed(2)+'%':'belum dapat dinilai'} · ${own.filter(r=>r.status==='unknown').length} jam tidak diketahui`)});el('summary').textContent=summaries.join(' | ')}
el('apply').onclick=draw;el('files').textContent=JSON.stringify(data.files,null,2);draw();</script></html>'''
    (output / 'availability.html').write_text(page.replace('PAYLOAD', payload), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--config', type=Path, default=Path(__file__).resolve().parent / 'config.json')
    parser.add_argument('--start', help='UTC atau ALL, inclusive')
    parser.add_argument('--end', help='UTC atau ALL, exclusive')
    parser.add_argument('--volcano', nargs='+', help='Nama gunung atau ALL')
    parser.add_argument('--station', nargs='+', help='MARKER NAME, kode folder, GUNUNG/STASIUN, atau ALL')
    parser.add_argument('--time-scale', choices=['utc', 'header'])
    parser.add_argument('--images', choices=['auto', 'hourly', 'daily', 'both', 'none'])
    parser.add_argument('--image-format', choices=['png', 'jpeg', 'both'])
    parser.add_argument('--dpi', type=int, help='150 untuk berbagi, 300 untuk laporan')
    parser.add_argument('--title')
    parser.add_argument('--from-report', type=Path, help='Ekspor gambar dari availability.json tanpa konversi ulang')
    args = parser.parse_args()
    if not args.config.is_file():
        parser.error(f'Config tidak ditemukan: {args.config}')
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    base = args.config.resolve().parent
    args.root = args.root.resolve() if args.root else resolve_path(config.get('data_directory', 'rawdata'), base)
    args.output = args.output.resolve() if args.output else resolve_path(config.get('output_directory', 'output'), base)
    period = config.get('period', {})
    try:
        args.start = period_value(args.start if args.start is not None else period.get('start', 'ALL'), date_arg)
        args.end = period_value(args.end if args.end is not None else period.get('end', 'ALL'), date_arg)
    except ValueError as exc:
        parser.error(f'Periode tidak valid: {exc}')
    if args.start and args.end and args.end <= args.start:
        parser.error('Akhir periode harus setelah awal periode (akhir eksklusif)')
    if args.volcano is not None:
        config['volcanoes'] = args.volcano
    if args.station is not None:
        config['station_filter'] = args.station
    image_cfg = config.get('image', {})
    args.time_scale = args.time_scale or config.get('time_scale', 'utc')
    args.images = args.images or image_cfg.get('mode', 'auto')
    args.image_format = args.image_format or image_cfg.get('format', 'both')
    args.dpi = args.dpi if args.dpi is not None else image_cfg.get('dpi', 150)
    args.title = args.title if args.title is not None else image_cfg.get('title', 'GNSS observation availability')
    for value, allowed in [(args.time_scale, ['utc', 'header']), (args.images, ['auto', 'hourly', 'daily', 'both', 'none']), (args.image_format, ['png', 'jpeg', 'both']), (config.get('station_name_source', 'header'), ['header', 'folder']), (config.get('data_layout', 'auto'), ['auto', 'volcano_station', 'station'])]:
        if value not in allowed:
            parser.error(f'Nilai konfigurasi {value!r} harus salah satu {allowed}')
    if not 50 <= args.dpi <= 600:
        parser.error('--dpi harus antara 50 dan 600')
    if args.from_report:
        rows = json.loads(args.from_report.read_text(encoding='utf-8'))
        rows = [r for r in rows if selected_row(r, config) and (args.start is None or date_arg(r['hour_utc']) >= args.start) and (args.end is None or date_arg(r['hour_utc']) < args.end)]
        if not rows:
            parser.error('Tidak ada data dalam rentang yang dipilih')
    else:
        rows = None
    if rows is None and not args.root.is_dir():
        parser.error('Folder rawdata tidak ditemukan')
    if rows is None:
        stations, files = analyze(args.root.resolve(), config, args.time_scale, args.start, args.end)
        if not stations:
            parser.error('Tidak ditemukan file GNSS yang didukung')
        rows = build_rows(stations, config, args.start, args.end)
        write_report(args.output, rows, files)
        print(f'HTML: {(args.output / "availability.html").resolve()}')
        print(f'File dianalisis: {sum(f["status"] == "ok" for f in files)}/{len(files)}; sisanya lihat files.json')
    groups = [(args.output, rows)]
    if config.get('split_by_volcano', True):
        for volcano in sorted({r.get('volcano', '') for r in rows} - {''}):
            slug = re.sub(r'[^A-Za-z0-9_-]', '_', volcano)
            group = [r for r in rows if r.get('volcano') == volcano]
            folder = args.output / slug
            groups.append((folder, group))
            if not args.from_report:
                write_report(folder, group, [f for f in files if f.get('volcano') == volcano])
    if args.images != 'none':
        from availability_images import write_images
        formats = ('png', 'jpeg') if args.image_format == 'both' else (args.image_format,)
        try:
            images = []
            for folder, group in groups:
                group_title = args.title if folder == args.output else f'{folder.name} - {args.title}'
                images.extend(write_images(folder, group, args.images, formats, args.dpi, group_title))
        except ImportError as exc:
            parser.error(f'Ekspor gambar memerlukan matplotlib: python -m pip install matplotlib ({exc})')
        for path in images:
            print(f'Gambar: {path.resolve()}')


if __name__ == '__main__':
    main()
