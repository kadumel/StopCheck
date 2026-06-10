from django.utils import timezone

from .models import DailyComparison, StopEvent


def get_or_create_today_comparison(organization, driver, vehicle=None):
    today = timezone.localdate()
    vehicle = vehicle or driver.default_vehicle
    comp, _ = DailyComparison.objects.get_or_create(
        organization=organization,
        driver=driver,
        date=today,
        defaults={'vehicle': vehicle},
    )
    if vehicle and not comp.vehicle:
        comp.vehicle = vehicle
        comp.save(update_fields=['vehicle'])
    return comp


def log_stop_event(organization, driver, event_type, vehicle=None, notes=''):
    vehicle = vehicle or driver.default_vehicle
    comp = get_or_create_today_comparison(organization, driver, vehicle)

    StopEvent.objects.create(
        organization=organization,
        driver=driver,
        vehicle=vehicle,
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
