# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0019_subscription_payment_flow'),
    ]

    operations = [
        migrations.AddField(
            model_name='dailycomparison',
            name='driver_data_locked',
            field=models.BooleanField(
                default=False,
                help_text='Quando activo, o motorista não pode alterar os seus dados.',
                verbose_name='Dados motorista bloqueados',
            ),
        ),
        migrations.AddField(
            model_name='dailycomparison',
            name='driver_submitted_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='Registo motorista concluído em',
            ),
        ),
    ]
