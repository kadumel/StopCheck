from decimal import Decimal as D

from django.db import migrations, models
import django.core.validators


def backfill_fuel_total_cost(apps, schema_editor):
    FuelRecord = apps.get_model('stop_check', 'FuelRecord')
    for record in FuelRecord.objects.iterator():
        record.total_cost = (record.liters * record.price_per_liter).quantize(D('0.01'))
        record.save(update_fields=['total_cost'])


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0012_driver_nif'),
    ]

    operations = [
        migrations.AddField(
            model_name='fuelrecord',
            name='total_cost',
            field=models.DecimalField(
                decimal_places=2,
                max_digits=10,
                null=True,
                validators=[django.core.validators.MinValueValidator(D('0.01'))],
                verbose_name='Valor Total (€)',
            ),
        ),
        migrations.RunPython(backfill_fuel_total_cost, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='fuelrecord',
            name='total_cost',
            field=models.DecimalField(
                decimal_places=2,
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(D('0.01'))],
                verbose_name='Valor Total (€)',
            ),
        ),
    ]
