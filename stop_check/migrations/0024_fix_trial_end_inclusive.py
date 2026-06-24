from datetime import timedelta

from django.db import migrations


def fix_trial_end_dates(apps, schema_editor):
    Subscription = apps.get_model('stop_check', 'Subscription')
    SubscriptionTariff = apps.get_model('stop_check', 'SubscriptionTariff')
    tariff = SubscriptionTariff.objects.first()
    trial_days = tariff.trial_days if tariff else 31

    for subscription in Subscription.objects.all():
        expected = subscription.start_date + timedelta(days=trial_days - 1)
        if subscription.trial_end_date != expected:
            subscription.trial_end_date = expected
            subscription.save(update_fields=['trial_end_date'])


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0023_route_addition_request'),
    ]

    operations = [
        migrations.RunPython(fix_trial_end_dates, migrations.RunPython.noop),
    ]
