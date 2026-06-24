from django.db import migrations, models

CONTRACTING_COMPANIES = [
    'CTT Expresso',
    'DHL',
    'UPS',
    'FedEx / TNT',
    'GLS',
    'DPD',
    'SEUR',
    'NACEX',
    'MRW',
    'Correos Express',
    'Chronopost',
    'InPost',
    'Paack',
    'Amazon Logistics',
    'VASP Expresso',
    'Torrestir',
    'Rangel Logistics Solutions',
    'Transdev Logistics',
    'Carglass Logistics',
    'Ecoscooting',
]


def seed_contracting_companies(apps, schema_editor):
    ContractingCompany = apps.get_model('stop_check', 'ContractingCompany')
    for index, name in enumerate(CONTRACTING_COMPANIES, start=1):
        ContractingCompany.objects.get_or_create(
            name=name,
            defaults={'sort_order': index, 'is_active': True},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0024_fix_trial_end_inclusive'),
    ]

    operations = [
        migrations.CreateModel(
            name='ContractingCompany',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, unique=True, verbose_name='Nome')),
                ('sort_order', models.PositiveSmallIntegerField(default=0, verbose_name='Ordem')),
                ('is_active', models.BooleanField(default=True, verbose_name='Ativa')),
            ],
            options={
                'verbose_name': 'Empresa Contratante',
                'verbose_name_plural': 'Empresas Contratantes',
                'ordering': ['sort_order', 'name'],
            },
        ),
        migrations.AddField(
            model_name='organization',
            name='contracting_company',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.PROTECT,
                related_name='organizations',
                to='stop_check.contractingcompany',
                verbose_name='Empresa Contratante',
            ),
        ),
        migrations.RunPython(seed_contracting_companies, migrations.RunPython.noop),
    ]
