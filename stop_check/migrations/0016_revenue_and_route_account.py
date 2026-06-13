from decimal import Decimal as D

from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


def backfill_company_route_revenue_accounts(apps, schema_editor):
    CompanyRoute = apps.get_model('stop_check', 'CompanyRoute')
    FinancialAccount = apps.get_model('stop_check', 'FinancialAccount')
    for route in CompanyRoute.objects.filter(revenue_account__isnull=True).iterator():
        account = (
            FinancialAccount.objects.filter(
                organization_id=route.organization_id,
                account_type='revenue',
                name='Entregas',
            ).first()
            or FinancialAccount.objects.filter(
                organization_id=route.organization_id,
                account_type='revenue',
            ).order_by('name').first()
        )
        if account:
            route.revenue_account_id = account.pk
            route.save(update_fields=['revenue_account_id'])


def backfill_revenues(apps, schema_editor):
    DailyComparison = apps.get_model('stop_check', 'DailyComparison')
    Revenue = apps.get_model('stop_check', 'Revenue')
    FinancialAccount = apps.get_model('stop_check', 'FinancialAccount')
    Route = apps.get_model('stop_check', 'Route')
    CompanyRoute = apps.get_model('stop_check', 'CompanyRoute')

    for comp in DailyComparison.objects.iterator():
        driver_total = comp.driver_stops + comp.driver_pudo + comp.driver_pickups
        if driver_total <= 0:
            continue

        route = None
        company_route = None
        if comp.route_id:
            route = Route.objects.filter(pk=comp.route_id).select_related('delivery_company').first()
            if route and route.company_route_id:
                company_route = CompanyRoute.objects.filter(pk=route.company_route_id).first()

        if company_route and company_route.revenue_account_id:
            account_id = company_route.revenue_account_id
        else:
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
            account_id = account.pk if account else None

        if company_route:
            price_per_stop = company_route.price_per_stop
            price_per_pudo = company_route.price_per_pudo
            price_per_pickup = company_route.price_per_pickup
            daily_rate = company_route.daily_rate
        else:
            RateConfig = apps.get_model('stop_check', 'RateConfig')
            config = RateConfig.objects.filter(organization_id=comp.organization_id).first()
            if not config:
                continue
            price_per_stop = config.price_per_stop
            price_per_pudo = config.price_per_pudo
            price_per_pickup = config.price_per_pickup
            daily_rate = D('0')

        amount = (
            D(comp.driver_stops) * price_per_stop
            + D(comp.driver_pudo) * price_per_pudo
            + D(comp.driver_pickups) * price_per_pickup
            + daily_rate
        ).quantize(D('0.01'))
        if amount <= 0:
            continue

        if route and route.delivery_company_id:
            route_label = f'{route.delivery_company.name} / {route.name}'
        elif route:
            route_label = route.name
        else:
            Driver = apps.get_model('stop_check', 'Driver')
            driver = Driver.objects.filter(pk=comp.driver_id).first()
            route_label = driver.name if driver else 'Produção'

        Revenue.objects.update_or_create(
            comparison_id=comp.pk,
            defaults={
                'organization_id': comp.organization_id,
                'account_id': account_id,
                'route_id': comp.route_id,
                'date': comp.date,
                'description': f'{route_label} — {comp.date.strftime("%d/%m/%Y")}',
                'amount': amount,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0015_default_revenue_account'),
    ]

    operations = [
        migrations.AddField(
            model_name='companyroute',
            name='revenue_account',
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={'account_type': 'revenue'},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='company_routes',
                to='stop_check.financialaccount',
                verbose_name='Plano de conta (Receita)',
            ),
        ),
        migrations.CreateModel(
            name='Revenue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(verbose_name='Data')),
                ('description', models.CharField(max_length=255, verbose_name='Descrição')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10, validators=[django.core.validators.MinValueValidator(D('0.01'))], verbose_name='Valor (€)')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='revenues', to='stop_check.financialaccount', verbose_name='Plano de conta')),
                ('comparison', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='revenue_entry', to='stop_check.dailycomparison')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='revenues', to='stop_check.organization')),
                ('route', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='revenues', to='stop_check.route')),
            ],
            options={
                'verbose_name': 'Receita',
                'verbose_name_plural': 'Receitas',
                'ordering': ['-date', '-created_at'],
            },
        ),
        migrations.RunPython(backfill_company_route_revenue_accounts, migrations.RunPython.noop),
        migrations.RunPython(backfill_revenues, migrations.RunPython.noop),
    ]
