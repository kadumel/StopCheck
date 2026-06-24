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
    Revenue = apps.get_model('stop_check', 'Revenue')
    from stop_check.models import DailyComparison
    from stop_check.services.revenue_service import sync_revenue_for_comparison

    comparison_ids = Revenue.objects.filter(
        comparison__isnull=False,
    ).values_list('comparison_id', flat=True).distinct()
    for comparison in DailyComparison.objects.filter(pk__in=comparison_ids):
        sync_revenue_for_comparison(comparison)


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
