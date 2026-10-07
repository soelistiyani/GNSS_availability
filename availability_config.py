"""Configuration, station identity and filters shared by scan/report export."""
import re
from pathlib import Path


def selection_matches(selection, *names):
    values = [selection] if isinstance(selection, str) else selection
    if values is None:
        return True
    values = {str(v).strip().upper() for v in values}
    return 'ALL' in values or any(str(n).upper() in values for n in names)


def folder_identity(relative_path, root, layout='auto'):
    parts = relative_path.parts
    multi = layout == 'volcano_station' or (layout == 'auto' and len(parts) > 2 and not re.match(r'^(20\d{2}|Ref\.Data)', parts[1], re.I))
    if multi:
        return parts[0].upper(), parts[1].upper()
    return root.name.upper(), parts[0].upper()


def header_station(data):
    text = data.decode('ascii', errors='replace').replace('\r\r\n', '\n').replace('\r\n', '\n').replace('\r', '\n')
    for line in text.splitlines():
        if line[60:].strip() == 'MARKER NAME':
            name = line[:60].strip().upper()
            return '' if name.strip('- ') in ('UNKNOWN', 'NONE', 'N/A') else name
        if line[60:].strip() == 'END OF HEADER':
            break
    return ''


def period_value(value, parse_date):
    return None if value is None or str(value).upper() == 'ALL' else parse_date(value)


def resolve_path(value, base):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def selected_row(row, config):
    return selection_matches(config.get('volcanoes', 'ALL'), row.get('volcano', '')) and selection_matches(
        config.get('station_filter', 'ALL'), row['station'], row.get('station_name', row['station']), row.get('folder_station', ''))
