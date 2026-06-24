from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0025_contracting_company'),
    ]

    operations = [
        migrations.AlterField(
            model_name='fuelrecord',
            name='liters',
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=8, null=True, verbose_name='Litros',
            ),
        ),
        migrations.AlterField(
            model_name='fuelrecord',
            name='price_per_liter',
            field=models.DecimalField(
                blank=True, decimal_places=3, max_digits=6, null=True,
                verbose_name='Preço/Litro (€)',
            ),
        ),
    ]
