from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0018_subscription_tariff_routes'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='subscription',
            name='additional_hours',
        ),
        migrations.RemoveField(
            model_name='subscription',
            name='trial_end_date',
        ),
        migrations.RemoveField(
            model_name='subscriptiontariff',
            name='price_additional_hour',
        ),
        migrations.RemoveField(
            model_name='subscriptiontariff',
            name='trial_days',
        ),
        migrations.AddField(
            model_name='subscription',
            name='contracted_routes',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Rotas contratadas'),
        ),
        migrations.AddField(
            model_name='subscription',
            name='payment_method',
            field=models.CharField(
                blank=True,
                choices=[('mbway', 'MB Way'), ('transfer', 'Transferência bancária')],
                max_length=20,
                verbose_name='Forma de pagamento',
            ),
        ),
        migrations.AddField(
            model_name='subscription',
            name='payment_reported_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Pagamento informado em'),
        ),
        migrations.AddField(
            model_name='subscriptiontariff',
            name='iban',
            field=models.CharField(blank=True, max_length=34, verbose_name='IBAN'),
        ),
        migrations.AddField(
            model_name='subscriptiontariff',
            name='iban_holder',
            field=models.CharField(blank=True, max_length=200, verbose_name='Titular da conta'),
        ),
        migrations.AddField(
            model_name='subscriptiontariff',
            name='mbway_phone',
            field=models.CharField(blank=True, max_length=20, verbose_name='Número MB Way'),
        ),
        migrations.AddField(
            model_name='subscriptiontariff',
            name='payment_notification_email',
            field=models.EmailField(
                blank=True,
                help_text='Recebe alerta quando um cliente informa que pagou.',
                max_length=254,
                verbose_name='Email para avisos de pagamento',
            ),
        ),
        migrations.AlterField(
            model_name='subscription',
            name='status',
            field=models.CharField(
                choices=[
                    ('active', 'Ativa'),
                    ('trial', 'Período Experimental'),
                    ('pending', 'Pagamento Pendente'),
                    ('suspended', 'Suspensa'),
                    ('cancelled', 'Cancelada'),
                ],
                default='trial',
                max_length=20,
            ),
        ),
    ]
