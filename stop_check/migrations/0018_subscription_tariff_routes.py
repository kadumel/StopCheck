from decimal import Decimal as D

from django.db import migrations, models
import django.core.validators


def create_default_tariff(apps, schema_editor):
    SubscriptionTariff = apps.get_model('stop_check', 'SubscriptionTariff')
    SubscriptionTariff.objects.get_or_create(
        pk=1,
        defaults={
            'trial_days': 31,
            'price_first_route': D('20.00'),
            'price_additional_route': D('5.00'),
            'price_additional_hour': D('0.00'),
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0017_revenue_manual'),
    ]

    operations = [
        migrations.CreateModel(
            name='SubscriptionTariff',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('trial_days', models.PositiveIntegerField(default=31, verbose_name='Dias de trial')),
                ('price_first_route', models.DecimalField(decimal_places=2, default=D('20.00'), max_digits=8, validators=[django.core.validators.MinValueValidator(D('0'))], verbose_name='1ª rota (€/mês)')),
                ('price_additional_route', models.DecimalField(decimal_places=2, default=D('5.00'), max_digits=8, validators=[django.core.validators.MinValueValidator(D('0'))], verbose_name='Rota adicional (€/mês)')),
                ('price_additional_hour', models.DecimalField(decimal_places=2, default=D('0.00'), max_digits=8, validators=[django.core.validators.MinValueValidator(D('0'))], verbose_name='Hora adicional (€)')),
            ],
            options={
                'verbose_name': 'Tarifa de Assinatura',
                'verbose_name_plural': 'Tarifa de Assinatura',
            },
        ),
        migrations.AddField(
            model_name='subscription',
            name='additional_hours',
            field=models.DecimalField(decimal_places=2, default=D('0.00'), max_digits=8, validators=[django.core.validators.MinValueValidator(D('0'))], verbose_name='Horas adicionais (mês)'),
        ),
        migrations.RunPython(create_default_tariff, migrations.RunPython.noop),
    ]
