from django.db import migrations, models


def backfill_snapshot_daily_rate(apps, schema_editor):
    DailyComparison = apps.get_model('stop_check', 'DailyComparison')
    Revenue = apps.get_model('stop_check', 'Revenue')
    for revenue in Revenue.objects.filter(
        revenue_kind='daily_rate',
        comparison__isnull=False,
    ).iterator():
        DailyComparison.objects.filter(
            pk=revenue.comparison_id,
            snapshot_daily_rate__isnull=True,
        ).update(snapshot_daily_rate=revenue.amount)


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0027_company_route_daily_rate_account'),
    ]

    operations = [
        migrations.AddField(
            model_name='dailycomparison',
            name='snapshot_daily_rate',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Valor da diária no momento do primeiro lançamento de produtividade.',
                max_digits=8,
                null=True,
                verbose_name='Diária registada (€)',
            ),
        ),
        migrations.RunPython(backfill_snapshot_daily_rate, migrations.RunPython.noop),
    ]
