import calendar

from django.core.management.base import BaseCommand
from django.utils import timezone

from stop_check.services.billing_service import (
    generate_monthly_invoices_for_all,
    last_day_of_month,
    send_payment_reminders,
    suspend_overdue_subscriptions,
)


class Command(BaseCommand):
    help = 'Tarefas de cobrança da assinatura (gerar, lembrar, suspender).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--task',
            choices=['auto', 'generate', 'remind', 'suspend'],
            default='auto',
            help='Tarefa a executar (auto detecta pelo dia do mês).',
        )
        parser.add_argument(
            '--date',
            help='Data de referência AAAA-MM-DD (útil para testes).',
        )

    def handle(self, *args, **options):
        if options['date']:
            from datetime import date
            year, month, day = map(int, options['date'].split('-'))
            reference_date = date(year, month, day)
        else:
            reference_date = timezone.localdate()

        task = options['task']

        if task in ('auto', 'generate'):
            if task == 'generate' or reference_date == last_day_of_month(reference_date):
                count = generate_monthly_invoices_for_all(reference_date)
                self.stdout.write(self.style.SUCCESS(
                    f'Cobranças mensais geradas: {count}',
                ))

        if task in ('auto', 'remind'):
            if task == 'remind' or reference_date.day == 1:
                sent = send_payment_reminders(reference_date)
                self.stdout.write(self.style.SUCCESS(
                    f'Emails de cobrança enviados: {sent}',
                ))

        if task in ('auto', 'suspend'):
            suspended = suspend_overdue_subscriptions(reference_date)
            if suspended:
                self.stdout.write(self.style.WARNING(
                    f'Assinaturas suspensas: {suspended}',
                ))
