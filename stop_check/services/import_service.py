import csv
import io
import re
from datetime import datetime

from django.utils import timezone

from stop_check.models import DailyComparison, Driver, ImportBatch, Route


COLUMN_ALIASES = {
    'date': ['data', 'date', 'dia', 'dt'],
    'route': ['rota', 'route', 'codigo rota', 'código rota', 'servico', 'serviço'],
    'driver': ['motorista', 'driver', 'nome', 'entregador', 'courier', 'colaborador'],
    'stops': ['paradas', 'stops', 'entregas', 'deliveries', 'stop'],
    'pudo': ['pudo', 'ponto pudo', 'pontos pudo', 'locker'],
    'pickups': ['recolhas', 'pickups', 'recolha', 'coletas', 'coleta', 'pickup'],
}


def _normalize_header(header):
    return re.sub(r'\s+', ' ', header.strip().lower())


def _match_column(header):
    normalized = _normalize_header(header)
    for field, aliases in COLUMN_ALIASES.items():
        if normalized in aliases or any(a in normalized for a in aliases):
            return field
    return None


def _parse_date(value):
    value = str(value).strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d.%m.%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f'Data inválida: {value}')


def _parse_int(value, default=0):
    if value is None or str(value).strip() == '':
        return default
    return int(float(str(value).replace(',', '.')))


def _read_rows(uploaded_file):
    name = uploaded_file.name.lower()
    content = uploaded_file.read()
    if isinstance(content, bytes):
        for encoding in ('utf-8-sig', 'latin-1', 'cp1252'):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = content.decode('utf-8', errors='replace')
    else:
        text = content

    if name.endswith(('.xlsx', '.xls')):
        try:
            import openpyxl
        except ImportError:
            raise ValueError('Instale openpyxl para importar ficheiros Excel.')
        wb = openpyxl.load_workbook(io.BytesIO(content if isinstance(content, bytes) else content.encode()), read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return [], {}
        headers = [str(h or '') for h in rows[0]]
        data_rows = rows[1:]
        mapping = {}
        for i, h in enumerate(headers):
            col = _match_column(h)
            if col:
                mapping[col] = i
        parsed = []
        for row in data_rows:
            if not any(row):
                continue
            parsed.append({k: row[i] if i < len(row) else None for k, i in mapping.items()})
        return parsed, mapping

    delimiter = ';' if text.count(';') > text.count(',') else ','
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return [], {}
    headers = rows[0]
    mapping = {}
    for i, h in enumerate(headers):
        col = _match_column(h)
        if col:
            mapping[col] = i
    parsed = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row if cell):
            continue
        parsed.append({k: row[i] if i < len(row) else '' for k, i in mapping.items()})
    return parsed, mapping


def _find_driver(organization, name):
    name = str(name).strip()
    if not name:
        return None
    driver = Driver.objects.filter(
        organization=organization, name__iexact=name, is_active=True
    ).first()
    if driver:
        return driver
    return Driver.objects.filter(
        organization=organization, name__icontains=name, is_active=True
    ).first()


def process_import_batch(batch):
    from stop_check.models import ImportBatch

    batch.status = ImportBatch.STATUS_PROCESSING
    batch.save(update_fields=['status'])

    org = batch.organization
    errors = []
    updated = 0
    failed = 0

    try:
        rows, mapping = _read_rows(batch.file)
    except Exception as exc:
        batch.status = ImportBatch.STATUS_FAILED
        batch.error_log = str(exc)
        batch.save()
        return batch

    if 'date' not in mapping and rows:
        errors.append('Coluna de data não encontrada. Use: data, date ou dia.')
    if 'driver' not in mapping:
        errors.append('Coluna de motorista não encontrada. Use: motorista, driver ou nome.')

    if errors:
        batch.status = ImportBatch.STATUS_FAILED
        batch.error_log = '\n'.join(errors)
        batch.save()
        return batch

    for idx, row in enumerate(rows, start=2):
        batch.rows_processed += 1
        try:
            date_val = _parse_date(row.get('date', ''))
            driver = _find_driver(org, row.get('driver', ''))
            if not driver:
                raise ValueError(f'Motorista não encontrado: {row.get("driver")}')

            vehicle = driver.default_vehicle
            if not vehicle:
                raise ValueError(f'Motorista sem veículo: {driver.name}')

            route_name = str(row.get('route', '')).strip() or driver.name
            route, _ = Route.objects.get_or_create(
                organization=org,
                name=route_name,
                date=date_val,
                defaults={
                    'driver': driver,
                    'vehicle': vehicle,
                },
            )
            if route.driver_id != driver.id:
                raise ValueError(
                    f'Rota "{route_name}" em {date_val} já atribuída a outro motorista'
                )

            comp, _ = DailyComparison.objects.get_or_create(
                route=route,
                defaults={
                    'organization': org,
                    'driver': driver,
                    'vehicle': vehicle,
                    'date': date_val,
                },
            )
            comp.sync_from_route()
            comp.company_stops = _parse_int(row.get('stops'), comp.company_stops)
            comp.company_pudo = _parse_int(row.get('pudo'), comp.company_pudo)
            comp.company_pickups = _parse_int(row.get('pickups'), comp.company_pickups)
            comp.save()
            updated += 1
        except Exception as exc:
            failed += 1
            errors.append(f'Linha {idx}: {exc}')

    batch.rows_updated = updated
    batch.rows_failed = failed
    batch.error_log = '\n'.join(errors[:50])
    batch.status = (
        ImportBatch.STATUS_COMPLETED if updated > 0 else ImportBatch.STATUS_FAILED
    )
    batch.save()
    return batch
