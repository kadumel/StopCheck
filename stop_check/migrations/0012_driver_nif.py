from django.db import migrations, models


def backfill_driver_nif(apps, schema_editor):
    Driver = apps.get_model('stop_check', 'Driver')
    User = apps.get_model('auth', 'User')
    used = set()

    for driver in Driver.objects.order_by('pk'):
        nif = None
        username = None
        if driver.user_id:
            username = User.objects.filter(pk=driver.user_id).values_list('username', flat=True).first()
            if username and username.isdigit() and len(username) == 9:
                nif = username
        if not nif:
            base = f'{driver.pk:09d}'[-9:]
            nif = base
            counter = 0
            while nif in used or Driver.objects.filter(nif=nif).exists():
                counter += 1
                nif = f'{counter:09d}'
        driver.nif = nif
        used.add(nif)
        driver.save(update_fields=['nif'])

        if driver.user_id and username and username != nif:
            User.objects.filter(pk=driver.user_id).update(username=nif)


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0011_backfill_comparisons'),
    ]

    operations = [
        migrations.AddField(
            model_name='driver',
            name='nif',
            field=models.CharField(max_length=9, null=True, unique=True, verbose_name='NIF'),
        ),
        migrations.RunPython(backfill_driver_nif, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='driver',
            name='nif',
            field=models.CharField(max_length=9, unique=True, verbose_name='NIF'),
        ),
    ]
