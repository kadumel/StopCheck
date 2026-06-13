from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0016_revenue_and_route_account'),
    ]

    operations = [
        migrations.AddField(
            model_name='revenue',
            name='notes',
            field=models.TextField(blank=True, verbose_name='Observações'),
        ),
        migrations.AddField(
            model_name='revenue',
            name='vehicle',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='revenues',
                to='stop_check.vehicle',
            ),
        ),
        migrations.AlterField(
            model_name='revenue',
            name='comparison',
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='revenue_entry',
                to='stop_check.dailycomparison',
            ),
        ),
    ]
