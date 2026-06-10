from django.utils import timezone

from .models import DailyComparison, Route, StopEvent


def get_today_routes(organization, driver):
    today = timezone.localdate()
    return Route.objects.filter(
        organization=organization,
        driver=driver,
        date=today,
        is_active=True,
    ).select_related('vehicle', 'comparison')


def get_route_for_logging(organization, driver, route_id=None):
    routes = get_today_routes(organization, driver)
    if route_id:
        return routes.filter(pk=route_id).first()
    if routes.count() == 1:
        return routes.first()
    return None


def ensure_route_for_driver(organization, driver, vehicle=None):
    """Cria rota do dia se o motorista só tiver uma atribuição implícita."""
    today = timezone.localdate()
    existing = get_today_routes(organization, driver)
    if existing.exists():
        return existing.first()

    vehicle = vehicle or driver.default_vehicle
    if not vehicle:
        return None

    return Route.objects.create(
        organization=organization,
        name=f'Rota {driver.name}',
        date=today,
        driver=driver,
        vehicle=vehicle,
    )


def get_or_create_comparison_for_route(route):
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
        comp.save(update_fields=['organization', 'driver', 'vehicle', 'date'])
    return comp


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

    vehicle = route.vehicle
    comp = get_or_create_comparison_for_route(route)

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
