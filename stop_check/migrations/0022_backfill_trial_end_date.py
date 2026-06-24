from datetime import timedelta

from django.db import migrations


def backfill_trial_end_dates(apps, schema_editor):
    Subscription = apps.get_model('stop_check', 'Subscription')
    SubscriptionTariff = apps.get_model('stop_check', 'SubscriptionTariff')
    tariff = SubscriptionTariff.objects.first()
    trial_days = tariff.trial_days if tariff else 31

    for subscription in Subscription.objects.filter(trial_end_date__isnull=True):
        subscription.trial_end_date = subscription.start_date + timedelta(days=trial_days)
        subscription.save(update_fields=['trial_end_date'])


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0021_subscription_billing'),
    ]

    operations = [
        migrations.RunPython(backfill_trial_end_dates, migrations.RunPython.noop),
    ]
