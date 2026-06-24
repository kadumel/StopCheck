from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def backfill_daily_rate_accounts(apps, schema_editor):
    CompanyRoute = apps.get_model('stop_check', 'CompanyRoute')
    for route in CompanyRoute.objects.filter(
        daily_rate_account__isnull=True,
        revenue_account__isnull=False,
    ).iterator():
        route.daily_rate_account_id = route.revenue_account_id
        route.save(update_fields=['daily_rate_account_id'])


def backfill_revenue_kind(apps, schema_editor):
    Revenue = apps.get_model('stop_check', 'Revenue')
    Revenue.objects.filter(comparison__isnull=False, revenue_kind='').update(
        revenue_kind='productivity',
    )


def resync_split_revenues(apps, schema_editor):
    """Split combined revenue rows into productivity + daily_rate entries.

    Uses historical models only — snapshot_daily_rate is added in 0028.
    """
    DailyComparison = apps.get_model('stop_check', 'DailyComparison')
    Revenue = apps.get_model('stop_check', 'Revenue')
    FinancialAccount = apps.get_model('stop_check', 'FinancialAccount')
    Route = apps.get_model('stop_check', 'Route')
    CompanyRoute = apps.get_model('stop_check', 'CompanyRoute')
    RateConfig = apps.get_model('stop_check', 'RateConfig')
    Driver = apps.get_model('stop_check', 'Driver')
    DeliveryCompany = apps.get_model('stop_check', 'DeliveryCompany')

    KIND_PRODUCTIVITY = 'productivity'
    KIND_DAILY_RATE = 'daily_rate'

    comparison_ids = Revenue.objects.filter(
        comparison__isnull=False,
    ).values_list('comparison_id', flat=True).distinct()

    def revenue_account_id(comp, company_route):
        if company_route and company_route.revenue_account_id:
            return company_route.revenue_account_id
        account = (
            FinancialAccount.objects.filter(
                organization_id=comp.organization_id,
                account_type='revenue',
                name='Entregas',
            ).first()
            or FinancialAccount.objects.filter(
                organization_id=comp.organization_id,
                account_type='revenue',
            ).order_by('name').first()
        )
        return account.pk if account else None

    def daily_rate_account_id(comp, company_route):
        if company_route and company_route.daily_rate_account_id:
            return company_route.daily_rate_account_id
        return revenue_account_id(comp, company_route)

    def comparison_route_label(comp, route):
        if route:
            if route.delivery_company_id:
                company = DeliveryCompany.objects.filter(
                    pk=route.delivery_company_id,
                ).first()
                if company:
                    return f'{company.name} / {route.name}'
            return route.name
        driver = Driver.objects.filter(pk=comp.driver_id).first()
        return driver.name if driver else 'Produção'

    def comparison_rates(comp, company_route):
        if company_route:
            return (
                company_route.price_per_stop,
                company_route.price_per_pudo,
                company_route.price_per_pickup,
                company_route.daily_rate,
            )
        config = RateConfig.objects.filter(organization_id=comp.organization_id).first()
        if not config:
            return (Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0'))
        return (
            config.price_per_stop,
            config.price_per_pudo,
            config.price_per_pickup,
            Decimal('0'),
        )

    def sync_revenue_line(comp, route, *, kind, account_id, amount, description_suffix=''):
        amount = amount.quantize(Decimal('0.01'))
        if amount <= 0:
            Revenue.objects.filter(comparison_id=comp.pk, revenue_kind=kind).delete()
            return

        date_label = comp.date.strftime('%d/%m/%Y')
        label = comparison_route_label(comp, route)
        Revenue.objects.update_or_create(
            comparison_id=comp.pk,
            revenue_kind=kind,
            defaults={
                'organization_id': comp.organization_id,
                'account_id': account_id,
                'route_id': comp.route_id,
                'vehicle_id': comp.vehicle_id,
                'date': comp.date,
                'description': f'{label} — {date_label}{description_suffix}',
                'amount': amount,
            },
        )

    for comp in DailyComparison.objects.filter(pk__in=comparison_ids).iterator():
        has_productivity = (
            comp.driver_stops > 0
            or comp.driver_pudo > 0
            or comp.driver_pickups > 0
        )
        if not has_productivity:
            Revenue.objects.filter(comparison_id=comp.pk).delete()
            continue

        route = None
        company_route = None
        if comp.route_id:
            route = Route.objects.filter(pk=comp.route_id).first()
            if route and route.company_route_id:
                company_route = CompanyRoute.objects.filter(
                    pk=route.company_route_id,
                ).first()

        price_per_stop, price_per_pudo, price_per_pickup, daily_rate = comparison_rates(
            comp, company_route,
        )
        productivity_amount = (
            Decimal(comp.driver_stops) * price_per_stop
            + Decimal(comp.driver_pudo) * price_per_pudo
            + Decimal(comp.driver_pickups) * price_per_pickup
        )
        sync_revenue_line(
            comp,
            route,
            kind=KIND_PRODUCTIVITY,
            account_id=revenue_account_id(comp, company_route),
            amount=productivity_amount,
        )

        daily_amount = (daily_rate or Decimal('0')).quantize(Decimal('0.01'))
        sync_revenue_line(
            comp,
            route,
            kind=KIND_DAILY_RATE,
            account_id=daily_rate_account_id(comp, company_route),
            amount=daily_amount,
            description_suffix=' — Diária',
        )


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0026_fuelrecord_optional_liters'),
    ]

    operations = [
        migrations.AddField(
            model_name='companyroute',
            name='daily_rate_account',
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={'account_type': 'revenue'},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='company_routes_daily_rate',
                to='stop_check.financialaccount',
                verbose_name='Plano de conta (Diárias)',
            ),
        ),
        migrations.AddField(
            model_name='revenue',
            name='revenue_kind',
            field=models.CharField(
                blank=True,
                choices=[('productivity', 'Produtividade'), ('daily_rate', 'Diária')],
                max_length=20,
                verbose_name='Tipo de receita',
            ),
        ),
        migrations.AlterField(
            model_name='companyroute',
            name='revenue_account',
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={'account_type': 'revenue'},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='company_routes',
                to='stop_check.financialaccount',
                verbose_name='Plano de conta (Produtividade)',
            ),
        ),
        migrations.AlterField(
            model_name='revenue',
            name='comparison',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='revenue_entries',
                to='stop_check.dailycomparison',
            ),
        ),
        migrations.RunPython(backfill_daily_rate_accounts, migrations.RunPython.noop),
        migrations.RunPython(backfill_revenue_kind, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='revenue',
            constraint=models.UniqueConstraint(
                condition=models.Q(('comparison__isnull', False)),
                fields=('comparison', 'revenue_kind'),
                name='unique_comparison_revenue_kind',
            ),
        ),
        migrations.RunPython(resync_split_revenues, migrations.RunPython.noop),
    ]
