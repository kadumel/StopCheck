from decimal import Decimal

from django.db import migrations


def copy_org_rates_to_company_routes(apps, schema_editor):
    CompanyRoute = apps.get_model('stop_check', 'CompanyRoute')
    RateConfig = apps.get_model('stop_check', 'RateConfig')

    for config in RateConfig.objects.all().iterator():
        CompanyRoute.objects.filter(organization_id=config.organization_id).update(
            price_per_stop=config.price_per_stop,
            price_per_pudo=config.price_per_pudo,
            price_per_pickup=config.price_per_pickup,
            daily_rate=Decimal('0'),
        )


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0007_company_route_rates'),
    ]

    operations = [
        migrations.RunPython(copy_org_rates_to_company_routes, migrations.RunPython.noop),
    ]
