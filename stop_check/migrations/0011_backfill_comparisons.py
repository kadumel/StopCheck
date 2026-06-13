from django.db import migrations


def backfill_comparisons(apps, schema_editor):
    Route = apps.get_model('stop_check', 'Route')
    DailyComparison = apps.get_model('stop_check', 'DailyComparison')

    linked_route_ids = set(
        DailyComparison.objects.exclude(route_id__isnull=True).values_list('route_id', flat=True)
    )
    for route in Route.objects.exclude(pk__in=linked_route_ids).iterator():
        DailyComparison.objects.create(
            route=route,
            organization=route.organization,
            driver=route.driver,
            vehicle=route.vehicle,
            date=route.date,
        )

    for comp in DailyComparison.objects.iterator():
        driver_total = comp.driver_stops + comp.driver_pudo + comp.driver_pickups
        company_total = comp.company_stops + comp.company_pudo + comp.company_pickups
        comp.driver_data_status = 'filled' if driver_total > 0 else 'pending'
        comp.company_data_status = 'filled' if company_total > 0 else 'pending'
        comp.save(update_fields=['driver_data_status', 'company_data_status'])


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0010_comparison_data_status'),
    ]

    operations = [
        migrations.RunPython(backfill_comparisons, migrations.RunPython.noop),
    ]
