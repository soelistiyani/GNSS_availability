"""Static hourly/daily UTC figures; matplotlib is imported only when exporting."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone


def utc(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def summarize(rows):
    active = [r for r in rows if r['status'] != 'inactive']
    unknown = sum(r['status'] == 'unknown' or r.get('availability_percent') is None for r in active)
    known = [r for r in active if r['status'] != 'unknown' and r.get('availability_percent') is not None and r.get('expected_epochs')]
    expected = sum(r['expected_epochs'] for r in known)
    available = sum(r['expected_epochs'] * r['availability_percent'] / 100 for r in known)
    return {'percent': 100 * available / expected if expected else None,
            'unknown_hours': unknown, 'active_hours': len(active)}


def daily_cells(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['station'], row['hour_utc'][:10])].append(row)
    return {key: summarize(group) for key, group in groups.items()}


def write_images(output, rows, mode='auto', formats=('png', 'jpeg'), dpi=150, title='GNSS observation availability'):
    if not rows or mode == 'none':
        return []
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.patches import Patch, Rectangle

    output.mkdir(parents=True, exist_ok=True)
    stations = sorted({r['station'] for r in rows})
    first = min(utc(r['hour_utc']) for r in rows)
    end = max(utc(r['hour_utc']) for r in rows) + timedelta(hours=1)
    cmap = LinearSegmentedColormap.from_list('availability', ['#c1e7ca', '#168342'])
    missing, inactive, orange = '#c7cbd0', '#ffffff', '#e79026'
    written = []
    styles = [Patch(facecolor=missing, label='Kosong (0%)'), Patch(facecolor=cmap(.25), label='Parsial'),
              Patch(facecolor=cmap(1.), label='Lengkap (100%)'), Patch(facecolor=orange, label='Belum dinilai'),
              Patch(facecolor=inactive, edgecolor='#c7cbd0', label='Di luar periode aktif / laporan')]

    def cell_color(cell):
        if not cell['active_hours']:
            return inactive
        if cell['percent'] is None:
            return orange
        return missing if cell['percent'] == 0 else cmap(cell['percent'] / 100)

    def draw(ax, selected, start, stop, resolution):
        step = timedelta(hours=1) if resolution == 'hourly' else timedelta(days=1)
        count = round((stop - start) / step)
        empty = {'percent': None, 'active_hours': 0, 'unknown_hours': 0}
        cells = daily_cells(selected) if resolution == 'daily' else {
            (r['station'], r['hour_utc']): summarize([r]) for r in selected}
        image = np.ones((len(stations), count, 4))
        incomplete = []
        for y, station in enumerate(stations):
            for x in range(count):
                t = start + x * step
                key = t.strftime('%Y-%m-%d') if resolution == 'daily' else t.isoformat().replace('+00:00', 'Z')
                cell = cells.get((station, key), empty)
                color = cell_color(cell)
                image[y, x] = matplotlib.colors.to_rgba(color)
                if cell['unknown_hours'] and cell['percent'] is not None:
                    incomplete.append((x, y))
        left, right = mdates.date2num(start), mdates.date2num(stop)
        width = (right - left) / count
        ax.imshow(image, aspect='auto', interpolation='nearest', extent=[left, right, len(stations)-.5, -.5])
        for x, y in incomplete:
            ax.add_patch(Rectangle((left + x * width, y - .5), width, 1, fill=False, edgecolor=orange, linewidth=1.2))
        ax.set_yticks(range(len(stations)), stations)
        ax.tick_params(axis='y', length=0, labelsize=11)
        for y in range(len(stations) + 1):
            ax.axhline(y - .5, color='#e4e9ef', linewidth=.7)
        ax.xaxis_date()
        locator = mdates.AutoDateLocator(minticks=4, maxticks=10, tz=timezone.utc)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator, tz=timezone.utc))
        ax.grid(axis='x', color='#607080', alpha=.18)
        ax.set_xlim(left, right)
        ax.set_xlabel('Tanggal / waktu UTC' if resolution == 'hourly' else 'Tanggal UTC')
        for spine in ax.spines.values():
            spine.set_color('#d9e0e7')
        ax.text(1.015, 1.02, 'Cakupan | jam\nbelum dinilai', transform=ax.transAxes, fontsize=9, color='#536474')
        for y, station in enumerate(stations):
            summary = summarize([r for r in selected if r['station'] == station])
            value = f"{summary['percent']:.1f}%" if summary['percent'] is not None else '?'
            ax.text(1.015, y, f"{value} | {summary['unknown_hours']}", transform=ax.get_yaxis_transform(), va='center', fontsize=10)

    def save(fig, name):
        for fmt in formats:
            path = output / f'{name}.{fmt}'
            options = {'pil_kwargs': {'quality': 95}} if fmt == 'jpeg' else {}
            fig.savefig(path, dpi=dpi, facecolor='white', **options)
            written.append(path)
        plt.close(fig)

    resolutions = ['hourly', 'daily'] if mode == 'both' else [mode]
    if mode == 'auto':
        resolutions = ['hourly', 'daily'] if (end - first).days <= 62 else ['daily']
    for resolution in resolutions:
        if resolution == 'daily':
            start = first.replace(hour=0)
            stop = end if end.hour == 0 else end.replace(hour=0) + timedelta(days=1)
        else:
            start, stop = first, end
        years = sorted({utc(r['hour_utc']).year for r in rows})
        panels = len(years) if resolution == 'daily' and len(years) > 1 else 1
        height = max(4.2, 2.5 + panels * (1.05 + .43 * len(stations)))
        fig, axes = plt.subplots(panels, 1, figsize=(12, height), squeeze=False)
        label_margin = min(.28, max(.10, .055 + .008 * max(map(len, stations))))
        fig.subplots_adjust(left=label_margin, right=.84, top=1 - .95 / height, bottom=1.55 / height, hspace=.9)
        fig.suptitle(title, x=.10, ha='left', va='top', y=1 - .12 / height, fontsize=17, fontweight='bold')
        fig.text(.10, 1 - .47 / height, f"{first:%d %b %Y %H:%M} - {end:%d %b %Y %H:%M} UTC (akhir eksklusif) | {'per jam' if resolution == 'hourly' else 'per hari'}", fontsize=10, color='#536474')
        for i, ax in enumerate(axes[:, 0]):
            if panels > 1:
                year = years[i]
                a, b = datetime(year, 1, 1, tzinfo=timezone.utc), datetime(year+1, 1, 1, tzinfo=timezone.utc)
                selected = [r for r in rows if utc(r['hour_utc']).year == year]
                ax.set_title(str(year), loc='left', fontsize=11)
            else:
                a, b, selected = start, stop, rows
            draw(ax, selected, a, b, resolution)
        fig.legend(handles=styles, loc='lower left', bbox_to_anchor=(.095, .48 / height), ncol=3, frameon=False, fontsize=9)
        fig.text(.10, .17 / height, 'Kelengkapan epoch observasi; bukan akurasi posisi. Cakupan mengecualikan jam belum dinilai.\nGaris oranye: sebagian jam belum dinilai. Sinyal yang didukung konverter saja.', fontsize=8, color='#536474')
        save(fig, f'availability_{resolution}')
    return written
