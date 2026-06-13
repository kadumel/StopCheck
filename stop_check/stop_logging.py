from django.utils import timezone

from .models import DailyComparison, Route, StopEvent
from .services.production_service import ensure_comparison_for_route


class DriverDataLockedError(ValueError):
    pass


class PendingPastDaysError(ValueError):
    pass


def get_pending_past_comparisons(organization, driver):
    today = timezone.localdate()
    return (
        DailyComparison.objects.filter(
            organization=organization,
            driver=driver,
            date__lt=today,
            driver_data_locked=False,
            route__isnull=False,
            route__is_active=True,
        )
        .select_related('route', 'vehicle')
        .order_by('date')
    )


def get_required_work_date(organization, driver):
    pending = get_pending_past_comparisons(organization, driver).first()
    return pending.date if pending else None


def get_work_date(organization, driver):
    return get_required_work_date(organization, driver) or timezone.localdate()


def get_routes_for_date(organization, driver, work_date):
    return Route.objects.filter(
        organization=organization,
        driver=driver,
        date=work_date,
        is_active=True,
    ).select_related('vehicle', 'comparison')


def get_work_routes(organization, driver):
    work_date = get_work_date(organization, driver)
    return get_routes_for_date(organization, driver, work_date), work_date


def assert_can_work_on_route(organization, driver, route):
    required = get_required_work_date(organization, driver)
    allowed_date = required or timezone.localdate()
    if route.date != allowed_date:
        if required:
            raise PendingPastDaysError(
                f'Conclua primeiro o registo de {required.strftime("%d/%m/%Y")} '
                f'antes de registar outro dia.'
            )
        raise ValueError('Rota inválida para o dia actual.')


def assert_driver_can_edit(comp):
    if comp.driver_data_locked:
        raise DriverDataLockedError(
            'Registo concluído. Contacte o gestor para alterar os dados.'
        )


def submit_driver_data(comp):
    if comp.driver_data_locked:
        return comp
    comp.driver_data_locked = True
    comp.driver_submitted_at = timezone.now()
    comp.save()
    return comp


def unlock_driver_data(comp):
    comp.driver_data_locked = False
    comp.driver_submitted_at = None
    comp.save()
    return comp


def get_today_routes(organization, driver):
    return get_routes_for_date(organization, driver, timezone.localdate())


def get_route_for_logging(organization, driver, route_id=None):
    routes = get_work_routes(organization, driver)[0]
    if route_id:
        return routes.filter(pk=route_id).first()
    if routes.count() == 1:
        return routes.first()
    return None


def ensure_route_for_driver(organization, driver, vehicle=None):
    """Cria rota do dia se o motorista só tiver uma atribuição implícita."""
    if get_required_work_date(organization, driver):
        return None

    today = timezone.localdate()
    existing = get_today_routes(organization, driver)
    if existing.exists():
        return existing.first()

    vehicle = vehicle or driver.default_vehicle
    if not vehicle:
        return None

    route = Route.objects.create(
        organization=organization,
        name=f'Rota {driver.name}',
        date=today,
        driver=driver,
        vehicle=vehicle,
    )
    ensure_comparison_for_route(route)
    return route


def get_or_create_comparison_for_route(route):
    return ensure_comparison_for_route(route)


def get_or_create_today_comparison(organization, driver, vehicle=None, route=None):
    if route is None:
        route = get_route_for_logging(organization, driver)
    if route is None:
        route = ensure_route_for_driver(organization, driver, vehicle)
    if route is None:
        raise ValueError('Nenhuma rota atribuída para hoje. Peça ao gestor para criar uma rota.')
    return get_or_create_comparison_for_route(route)


def log_stop_event(organization, driver, event_type, vehicle=None, route=None, notes=''):
    route = route or get_route_for_logging(organization, driver)
    if route is None:
        route = ensure_route_for_driver(organization, driver, vehicle)
    if route is None:
        raise ValueError('Nenhuma rota atribuída para hoje.')

    assert_can_work_on_route(organization, driver, route)
    vehicle = route.vehicle
    comp = get_or_create_comparison_for_route(route)
    assert_driver_can_edit(comp)

    StopEvent.objects.create(
        organization=organization,
        driver=driver,
        vehicle=vehicle,
        route=route,
        event_type=event_type,
        notes=notes,
    )

    if event_type == StopEvent.TYPE_STOP:
        comp.driver_stops += 1
    elif event_type == StopEvent.TYPE_PUDO:
        comp.driver_pudo += 1
    elif event_type == StopEvent.TYPE_PICKUP:
        comp.driver_pickups += 1
    comp.save()

    return comp


def decrement_driver_count(comp, event_type):
    assert_driver_can_edit(comp)
    if event_type == StopEvent.TYPE_STOP:
        comp.driver_stops = max(0, comp.driver_stops - 1)
    elif event_type == StopEvent.TYPE_PUDO:
        comp.driver_pudo = max(0, comp.driver_pudo - 1)
    elif event_type == StopEvent.TYPE_PICKUP:
        comp.driver_pickups = max(0, comp.driver_pickups - 1)
    else:
        raise ValueError('Tipo inválido.')
    comp.save()
    return comp


def set_driver_counts(comp, stops, pudo, pickups):
    assert_driver_can_edit(comp)
    comp.driver_stops = max(0, int(stops))
    comp.driver_pudo = max(0, int(pudo))
    comp.driver_pickups = max(0, int(pickups))
    comp.save()
    return comp
