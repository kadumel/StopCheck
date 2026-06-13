from django.db import migrations


def populate_company_routes(apps, schema_editor):
    Route = apps.get_model('stop_check', 'Route')
    CompanyRoute = apps.get_model('stop_check', 'CompanyRoute')
    DeliveryCompany = apps.get_model('stop_check', 'DeliveryCompany')

    for route in Route.objects.filter(company_route__isnull=True).iterator():
        if not route.delivery_company_id:
            company, _ = DeliveryCompany.objects.get_or_create(
                organization_id=route.organization_id,
                name='Geral',
                defaults={'is_active': True},
            )
            route.delivery_company_id = company.pk
            route.save(update_fields=['delivery_company_id'])
        else:
            company = DeliveryCompany.objects.get(pk=route.delivery_company_id)

        company_route, _ = CompanyRoute.objects.get_or_create(
            organization_id=route.organization_id,
            delivery_company_id=company.pk,
            name=route.name,
            defaults={'is_active': True},
        )
        route.company_route_id = company_route.pk
        route.save(update_fields=['company_route_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0005_company_route'),
    ]

    operations = [
        migrations.RunPython(populate_company_routes, migrations.RunPython.noop),
    ]
