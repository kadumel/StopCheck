from django.db import migrations


def add_default_revenue_account(apps, schema_editor):
    Organization = apps.get_model('stop_check', 'Organization')
    FinancialAccount = apps.get_model('stop_check', 'FinancialAccount')
    for org in Organization.objects.iterator():
        if not FinancialAccount.objects.filter(
            organization=org, account_type='revenue',
        ).exists():
            FinancialAccount.objects.create(
                organization=org,
                name='Entregas',
                color='#059669',
                account_type='revenue',
            )


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0014_financial_account'),
    ]

    operations = [
        migrations.RunPython(add_default_revenue_account, migrations.RunPython.noop),
    ]
