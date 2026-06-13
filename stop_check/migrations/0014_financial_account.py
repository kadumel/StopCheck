from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stop_check', '0013_fuelrecord_total_cost'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='ExpenseCategory',
            new_name='FinancialAccount',
        ),
        migrations.RenameField(
            model_name='expense',
            old_name='category',
            new_name='account',
        ),
        migrations.AlterField(
            model_name='financialaccount',
            name='organization',
            field=models.ForeignKey(
                on_delete=models.CASCADE,
                related_name='financial_accounts',
                to='stop_check.organization',
            ),
        ),
        migrations.AddField(
            model_name='financialaccount',
            name='account_type',
            field=models.CharField(
                choices=[('expense', 'Despesa'), ('revenue', 'Receita')],
                default='expense',
                max_length=10,
                verbose_name='Tipo',
            ),
        ),
        migrations.AlterModelOptions(
            name='financialaccount',
            options={
                'verbose_name': 'Plano de Conta',
                'verbose_name_plural': 'Plano de Contas',
                'unique_together': {('organization', 'name')},
            },
        ),
    ]
