from calendar import monthrange
from datetime import date

from django.db.models import Q

from stop_check.models import DailyComparison, Route


def ensure_comparison_for_route(route):
    """Cria ou sincroniza o comparativo diário ligado à atribuição."""
    comp, created = DailyComparison.objects.get_or_create(
        route=route,
        defaults={
            'organization': route.organization,
            'driver': route.driver,
            'vehicle': route.vehicle,
            'date': route.date,
        },
    )
    if not created:
        comp.sync_from_route()
    comp.save()
    return comp


WEEKDAY_LABELS = [
    (0, 'Segunda'),
    (1, 'Terça'),
    (2, 'Quarta'),
    (3, 'Quinta'),
    (4, 'Sexta'),
    (5, 'Sábado'),
    (6, 'Domingo'),
]

DEFAULT_WEEKDAYS = {0, 1, 2, 3, 4}


def get_dates_for_month(year, month, weekdays):
    """Datas do mês cujo weekday() está em weekdays (0=segunda)."""
    weekdays = set(int(w) for w in weekdays)
    last = monthrange(year, month)[1]
    return [
        date(year, month, day)
        for day in range(1, last + 1)
        if date(year, month, day).weekday() in weekdays
    ]


def assignment_has_production_data(route):
    """Dia com stops/PUDO/recolhas registados não pode ser substituído."""
    try:
        comp = route.comparison
    except DailyComparison.DoesNotExist:
        comp = None

    if comp:
        if comp.driver_stops or comp.driver_pudo or comp.driver_pickups:
            return True
        if comp.company_stops or comp.company_pudo or comp.company_pickups:
            return True

    if route.stop_events.exists():
        return True
    return False


def find_existing_assignments(organization, company_route, dates):
    return Route.objects.filter(
        organization=organization,
        date__in=dates,
    ).filter(
        Q(company_route=company_route)
        | Q(company_route__isnull=True, name=company_route.name)
    ).select_related('driver', 'vehicle', 'comparison')


def analyze_schedule(organization, company_route, dates):
    existing_map = {r.date: r for r in find_existing_assignments(organization, company_route, dates)}

    new_dates = []
    replaceable = []
    protected = []

    for d in sorted(dates):
        route = existing_map.get(d)
        if route is None:
            new_dates.append(d)
        elif assignment_has_production_data(route):
            protected.append(route)
        else:
            replaceable.append(route)

    return {
        'new_dates': new_dates,
        'replaceable': replaceable,
        'protected': protected,
        'total_target': len(dates),
    }


def apply_assignments(organization, company_route, driver, vehicle, notes, is_active, analysis, replace_existing):
    created = 0
    replaced = 0

    for route in analysis['replaceable']:
        if not replace_existing:
            continue
        route.company_route = company_route
        route.driver = driver
        route.vehicle = vehicle
        route.notes = notes
        route.is_active = is_active
        route.save()
        ensure_comparison_for_route(route)
        replaced += 1

    for d in analysis['new_dates']:
        route = Route.objects.create(
            organization=organization,
            company_route=company_route,
            driver=driver,
            vehicle=vehicle,
            notes=notes,
            is_active=is_active,
            date=d,
            name=company_route.name,
            delivery_company=company_route.delivery_company,
        )
        ensure_comparison_for_route(route)
        created += 1

    return created, replaced, len(analysis['protected'])


def delete_assignments(organization, route_ids):
    """Elimina atribuições sem dados de produção. Devolve (eliminadas, bloqueadas)."""
    routes = Route.objects.filter(
        organization=organization,
        pk__in=route_ids,
    ).select_related('driver', 'vehicle', 'comparison')

    deleted = 0
    blocked = []

    for route in routes:
        if assignment_has_production_data(route):
            blocked.append(route)
        else:
            route.delete()
            deleted += 1

    return deleted, blocked
