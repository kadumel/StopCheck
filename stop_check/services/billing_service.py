import calendar
import logging
from datetime import date, timedelta

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from stop_check.models import (
    RouteAdditionRequest,
    Subscription,
    SubscriptionInvoice,
    SubscriptionTariff,
)

logger = logging.getLogger(__name__)


def first_day_of_month(value):
    return date(value.year, value.month, 1)


def last_day_of_month(value):
    return Subscription.month_end(value)


def next_month(value):
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def due_date_for_period(period_start, tariff=None):
    """Pagamento antecipado: vence no dia 5 do mês do período facturado."""
    tariff = tariff or SubscriptionTariff.get()
    return date(period_start.year, period_start.month, tariff.payment_due_day)


def _as_date(value):
    if value is None:
        return None
    if hasattr(value, 'date') and not isinstance(value, date):
        return value.date()
    return value


def resolve_contract_date(subscription, contract_date=None):
    """Data de início da cobrança proporcional na contratação."""
    return contract_date or timezone.localdate()


def create_initial_prorata_invoice(subscription, route_count, contract_date=None):
    """Cobrança proporcional da contratação até ao fim do mês."""
    contract_date = resolve_contract_date(subscription, contract_date)
    period_end = last_day_of_month(contract_date)
    monthly = Subscription.calculate_price(route_count)
    amount = Subscription.calculate_prorata(monthly, contract_date, period_end)
    due = due_date_for_period(next_month(contract_date))

    invoice, created = SubscriptionInvoice.objects.get_or_create(
        subscription=subscription,
        invoice_type=SubscriptionInvoice.TYPE_PRORATA_INITIAL,
        period_start=contract_date,
        period_end=period_end,
        defaults={
            'route_count': route_count,
            'amount': amount,
            'due_date': due,
        },
    )
    if not created and (
        invoice.amount != amount
        or invoice.route_count != route_count
        or invoice.due_date != due
    ):
        invoice.route_count = route_count
        invoice.amount = amount
        invoice.due_date = due
        invoice.save(update_fields=['route_count', 'amount', 'due_date'])
    return invoice, created


def create_monthly_invoice(subscription, period_start):
    """Gera cobrança mensal antecipada para o mês indicado."""
    period_end = last_day_of_month(period_start)
    route_count = subscription.contracted_routes or max(subscription.organization.route_count, 1)
    amount = Subscription.calculate_price(route_count)
    due = due_date_for_period(period_start)

    existing = SubscriptionInvoice.objects.filter(
        subscription=subscription,
        invoice_type=SubscriptionInvoice.TYPE_MONTHLY,
        period_start=period_start,
        period_end=period_end,
    ).first()
    if existing:
        return existing, False

    invoice = SubscriptionInvoice.objects.create(
        subscription=subscription,
        invoice_type=SubscriptionInvoice.TYPE_MONTHLY,
        period_start=period_start,
        period_end=period_end,
        route_count=route_count,
        amount=amount,
        due_date=due,
    )
    return invoice, True


def _period_line_from_prorata(label, monthly_amount, period_start, period_end, status=None):
    details = Subscription.calculate_prorata_details(
        monthly_amount, period_start, period_end,
    )
    return {
        'label': label,
        'start': period_start,
        'end': period_end,
        'is_prorata': not _is_full_month_period(period_start, period_end),
        'amount': details['amount'],
        'monthly_amount': details['monthly_amount'],
        'days_in_month': details['days_in_month'],
        'billable_days': details['billable_days'],
        'status': status,
    }


def calculate_subscription_prorata(route_count, period_start, period_end=None):
    """Valor proporcional da assinatura para N rotas no período indicado."""
    period_start = _as_date(period_start)
    period_end = _as_date(period_end) or last_day_of_month(period_start)
    monthly = Subscription.calculate_price(route_count)
    return Subscription.calculate_prorata(monthly, period_start, period_end)


def calculate_route_addition_prorata(additional_routes, request_date=None):
    """Valor proporcional para N rotas adicionais até ao fim do mês."""
    request_date = _as_date(request_date) or timezone.localdate()
    period_end = last_day_of_month(request_date)
    unit_monthly = Subscription.calculate_additional_route_price()
    unit_prorata = Subscription.calculate_prorata(unit_monthly, request_date, period_end)
    return unit_prorata * additional_routes


def create_route_addition_request(subscription, additional_routes, request_date=None):
    """
    Pedido de rotas adicionais na página de assinatura.
    Gera cobrança proporcional e fica pendente até confirmação do pagamento.
    """
    org = subscription.organization
    tariff = SubscriptionTariff.get()

    if not base_routes_registered(org, tariff):
        raise ValueError(
            f'Registre as {tariff.included_routes} rotas do plano base no catálogo '
            f'antes de contratar rotas adicionais.',
        )
    if not at_route_limit(subscription, org):
        raise ValueError(
            'Ainda tem vagas no plano actual. Registe as rotas disponíveis antes de solicitar mais.',
        )
    if subscription.has_pending_route_request():
        raise ValueError('Já existe um pedido de rotas adicionais aguardando pagamento.')

    request_date = request_date or timezone.localdate()
    period_end = last_day_of_month(request_date)
    amount = calculate_route_addition_prorata(additional_routes, request_date)
    due = due_date_for_period(next_month(request_date))

    with transaction.atomic():
        invoice = SubscriptionInvoice.objects.create(
            subscription=subscription,
            invoice_type=SubscriptionInvoice.TYPE_PRORATA_ROUTE,
            period_start=request_date,
            period_end=period_end,
            route_count=additional_routes,
            amount=amount,
            due_date=due,
        )
        route_request = RouteAdditionRequest.objects.create(
            subscription=subscription,
            additional_routes=additional_routes,
            invoice=invoice,
        )
    return route_request


def generate_monthly_invoices_for_all(reference_date=None):
    """Último dia do mês: gera cobranças do mês seguinte para assinaturas activas."""
    reference_date = reference_date or timezone.localdate()
    billing_month = next_month(reference_date)
    created_count = 0

    subscriptions = Subscription.objects.filter(
        status=Subscription.STATUS_ACTIVE,
        contracted_routes__isnull=False,
    ).select_related('organization')

    for subscription in subscriptions:
        _, created = create_monthly_invoice(subscription, billing_month)
        if created:
            created_count += 1

    logger.info(
        'Cobranças mensais geradas: %s novas para %s/%s',
        created_count, billing_month.month, billing_month.year,
    )
    return created_count


def send_payment_reminders(reference_date=None):
    """Dia 1: envia email de cobrança para facturas pendentes do mês."""
    from stop_check.services.email_service import send_subscription_invoice_reminder

    reference_date = reference_date or timezone.localdate()
    month_start = first_day_of_month(reference_date)
    month_end = last_day_of_month(reference_date)

    invoices = SubscriptionInvoice.objects.filter(
        status__in=(
            SubscriptionInvoice.STATUS_PENDING,
            SubscriptionInvoice.STATUS_OVERDUE,
        ),
        period_start__gte=month_start,
        period_start__lte=month_end,
    ).select_related('subscription__organization')

    sent = 0
    for invoice in invoices:
        try:
            send_subscription_invoice_reminder(invoice)
            sent += 1
        except Exception:
            logger.exception(
                'Falha ao enviar lembrete de cobrança #%s', invoice.pk,
            )
    return sent


def suspend_overdue_subscriptions(reference_date=None):
    """Após o dia 5: suspende assinaturas com cobranças em atraso."""
    reference_date = reference_date or timezone.localdate()
    tariff = SubscriptionTariff.get()
    if reference_date.day <= tariff.payment_due_day:
        return 0

    overdue_invoices = SubscriptionInvoice.objects.filter(
        status__in=(
            SubscriptionInvoice.STATUS_PENDING,
            SubscriptionInvoice.STATUS_OVERDUE,
        ),
        due_date__lt=reference_date,
    ).select_related('subscription')

    suspended = 0
    for invoice in overdue_invoices:
        invoice.status = SubscriptionInvoice.STATUS_OVERDUE
        invoice.save(update_fields=['status'])
        subscription = invoice.subscription
        if subscription.status == Subscription.STATUS_ACTIVE:
            subscription.status = Subscription.STATUS_SUSPENDED
            subscription.save(update_fields=['status'])
            suspended += 1
            logger.info(
                'Assinatura suspensa por falta de pagamento: %s',
                subscription.organization.name,
            )
    return suspended


@transaction.atomic
def activate_subscription_for_invoice(invoice, paid_date=None):
    """Activa a assinatura e recursos associados a uma cobrança paga."""
    paid_date = paid_date or invoice.paid_at or timezone.localdate()
    if invoice.paid_at is None:
        invoice.paid_at = paid_date
        invoice.save(update_fields=['paid_at'])
    subscription = invoice.subscription
    subscription.last_payment_date = paid_date
    subscription.payment_reported_at = None
    update_fields = ['last_payment_date', 'payment_reported_at']

    if invoice.invoice_type == SubscriptionInvoice.TYPE_PRORATA_INITIAL:
        subscription.status = Subscription.STATUS_ACTIVE
        subscription.contracted_routes = invoice.route_count
        update_fields.extend(['status', 'contracted_routes'])
    elif invoice.invoice_type == SubscriptionInvoice.TYPE_MONTHLY:
        if subscription.status in (
            Subscription.STATUS_PENDING,
            Subscription.STATUS_SUSPENDED,
        ):
            subscription.status = Subscription.STATUS_ACTIVE
            update_fields.append('status')
    elif invoice.invoice_type == SubscriptionInvoice.TYPE_PRORATA_ROUTE:
        subscription.contracted_routes = (
            (subscription.contracted_routes or 0) + invoice.route_count
        )
        update_fields.append('contracted_routes')
        route_request = getattr(invoice, 'route_request', None)
        if route_request:
            route_request.status = RouteAdditionRequest.STATUS_PAID
            route_request.save(update_fields=['status'])
        if subscription.status == Subscription.STATUS_SUSPENDED:
            has_overdue = subscription.invoices.filter(
                status__in=(
                    SubscriptionInvoice.STATUS_PENDING,
                    SubscriptionInvoice.STATUS_OVERDUE,
                ),
            ).exclude(pk=invoice.pk).exists()
            if not has_overdue:
                subscription.status = Subscription.STATUS_ACTIVE
                update_fields.append('status')

    subscription.save(update_fields=update_fields)
    return invoice


def sync_subscription_payment_state(subscription):
    """
    Corrige assinaturas pendentes/suspensas quando já existem cobranças pagas
    (ex.: estado alterado no admin sem activar a assinatura).
    """
    if subscription.status not in (
        Subscription.STATUS_PENDING,
        Subscription.STATUS_SUSPENDED,
    ):
        return subscription

    paid_invoices = subscription.invoices.filter(
        status=SubscriptionInvoice.STATUS_PAID,
    ).order_by('period_start', 'pk')

    for invoice in paid_invoices:
        if invoice.invoice_type == SubscriptionInvoice.TYPE_PRORATA_INITIAL:
            activate_subscription_for_invoice(invoice, invoice.paid_at)
            subscription.refresh_from_db()
            return subscription

    paid_monthly = paid_invoices.filter(
        invoice_type=SubscriptionInvoice.TYPE_MONTHLY,
    ).first()
    if paid_monthly and subscription.status == Subscription.STATUS_PENDING:
        activate_subscription_for_invoice(paid_monthly, paid_monthly.paid_at)
        subscription.refresh_from_db()

    return subscription


@transaction.atomic
def mark_invoice_paid(invoice, paid_date=None):
    """Confirma pagamento e activa recursos associados."""
    paid_date = paid_date or timezone.localdate()
    if invoice.status != SubscriptionInvoice.STATUS_PAID:
        invoice.status = SubscriptionInvoice.STATUS_PAID
        invoice.paid_at = paid_date
        invoice.save()
    else:
        activate_subscription_for_invoice(invoice, paid_date)
    return invoice


def report_invoice_payment(invoice):
    """Cliente informa que efectuou o pagamento."""
    invoice.payment_reported_at = timezone.now()
    invoice.save(update_fields=['payment_reported_at'])
    subscription = invoice.subscription
    subscription.payment_reported_at = timezone.now()
    subscription.save(update_fields=['payment_reported_at'])


def get_pending_invoices(subscription):
    return subscription.invoices.filter(
        status__in=(
            SubscriptionInvoice.STATUS_PENDING,
            SubscriptionInvoice.STATUS_OVERDUE,
        ),
    ).order_by('due_date', 'period_start')


def get_current_payable_invoice(subscription):
    return get_pending_invoices(subscription).first()


def get_catalog_route_limit(subscription, tariff=None):
    """Máximo de rotas registáveis no catálogo (trial/pendente: plano base)."""
    tariff = tariff or SubscriptionTariff.get()
    if subscription.status == Subscription.STATUS_ACTIVE:
        return subscription.contracted_routes or 0
    if subscription.status == Subscription.STATUS_TRIAL and subscription.is_trial_active:
        return tariff.included_routes
    if subscription.status == Subscription.STATUS_PENDING:
        return tariff.included_routes
    return 0


def route_limit_reached_message(subscription, tariff=None):
    tariff = tariff or SubscriptionTariff.get()
    if subscription.status == Subscription.STATUS_TRIAL and subscription.is_trial_active:
        return (
            f'Atingiu o limite de {tariff.included_routes} rotas do período experimental. '
            'Contrate um plano em Assinatura para adicionar mais rotas.'
        )
    if subscription.status == Subscription.STATUS_PENDING:
        return (
            f'Atingiu o limite de {tariff.included_routes} rotas até confirmação do pagamento. '
            'Após activação da assinatura, poderá registar as rotas contratadas.'
        )
    return (
        'Atingiu o limite de rotas do seu plano. '
        'Solicite rotas adicionais na página Assinatura.'
    )


def at_route_limit(subscription, org, tariff=None):
    """Sem vagas no plano para registar nova rota no catálogo."""
    limit = get_catalog_route_limit(subscription, tariff)
    if not limit:
        return org.route_count > 0
    return org.route_count >= limit


def base_routes_registered(org, tariff=None):
    """As rotas do plano base (ex.: 5) já estão no catálogo."""
    tariff = tariff or SubscriptionTariff.get()
    return org.route_count >= tariff.included_routes


def can_request_additional_routes(subscription, org, tariff=None):
    """Pode solicitar rotas pagas além do plano base."""
    tariff = tariff or SubscriptionTariff.get()
    if subscription.status != Subscription.STATUS_ACTIVE:
        return False
    if subscription.has_pending_route_request():
        return False
    if not at_route_limit(subscription, org):
        return False
    return base_routes_registered(org, tariff)


def get_pending_route_request(subscription):
    return subscription.route_requests.filter(
        status=RouteAdditionRequest.STATUS_PENDING,
    ).select_related('invoice').first()


def trial_days_remaining(subscription):
    if not subscription.trial_end_date:
        return None
    remaining = (subscription.trial_end_date - timezone.localdate()).days + 1
    return max(remaining, 0)


def _is_full_month_period(period_start, period_end):
    month_start = first_day_of_month(period_start)
    month_end = last_day_of_month(period_start)
    return period_start == month_start and period_end == month_end


def _get_prorata_initial_invoice(subscription):
    return subscription.invoices.filter(
        invoice_type=SubscriptionInvoice.TYPE_PRORATA_INITIAL,
    ).exclude(status=SubscriptionInvoice.STATUS_CANCELLED).order_by('period_start').first()


def _get_monthly_invoice_for_month(subscription, month_start):
    month_end = last_day_of_month(month_start)
    return subscription.invoices.filter(
        invoice_type=SubscriptionInvoice.TYPE_MONTHLY,
        period_start=month_start,
        period_end=month_end,
    ).exclude(status=SubscriptionInvoice.STATUS_CANCELLED).first()


def _expected_first_billing_period(subscription):
    """Período previsto quando ainda não há fatura mas a assinatura tem data de início."""
    start = get_subscription_start_date(subscription)
    if not start:
        return None
    end = last_day_of_month(start)
    route_count = subscription.contracted_routes or max(subscription.organization.route_count, 1)
    monthly = Subscription.calculate_price(route_count)
    is_prorata = not _is_full_month_period(start, end)
    if is_prorata:
        line = _period_line_from_prorata(
            'Primeira mensalidade (proporcional)', monthly, start, end,
        )
    else:
        days_in_month = calendar.monthrange(start.year, start.month)[1]
        line = {
            'label': 'Período da assinatura',
            'start': start,
            'end': end,
            'is_prorata': False,
            'amount': monthly,
            'monthly_amount': monthly,
            'days_in_month': days_in_month,
            'billable_days': (end - start).days + 1,
            'status': None,
        }
    return line


def _monthly_amount_for_invoice(invoice):
    if invoice.invoice_type == SubscriptionInvoice.TYPE_PRORATA_ROUTE:
        return Subscription.calculate_additional_route_price() * invoice.route_count
    return Subscription.calculate_price(invoice.route_count)


def _period_line_from_invoice(invoice, label=None):
    label = label or invoice.get_invoice_type_display()
    monthly = _monthly_amount_for_invoice(invoice)
    if _is_full_month_period(invoice.period_start, invoice.period_end):
        days_in_month = calendar.monthrange(
            invoice.period_start.year, invoice.period_start.month,
        )[1]
        return {
            'label': label,
            'start': invoice.period_start,
            'end': invoice.period_end,
            'is_prorata': False,
            'amount': invoice.amount,
            'monthly_amount': monthly,
            'days_in_month': days_in_month,
            'billable_days': (invoice.period_end - invoice.period_start).days + 1,
            'status': invoice.status,
        }
    line = _period_line_from_prorata(
        label, monthly, invoice.period_start, invoice.period_end, invoice.status,
    )
    line['amount'] = invoice.amount
    return line


def compute_contract_prorata_preview(subscription, route_count, contract_date=None):
    """Pré-visualização do valor proporcional na contratação."""
    contract_date = resolve_contract_date(subscription, contract_date)
    period_end = last_day_of_month(contract_date)
    monthly = Subscription.calculate_price(route_count)
    line = _period_line_from_prorata(
        'Contratação (proporcional)', monthly, contract_date, period_end,
    )
    return line


def compute_amount_due(subscription, today, monthly_price, current_invoice, period_info):
    if current_invoice:
        return current_invoice.amount
    if period_info.get('period_lines'):
        first = period_info['period_lines'][0]
        if first.get('amount') is not None:
            return first['amount']
    if subscription.status == Subscription.STATUS_TRIAL:
        return Decimal('0.00')
    return monthly_price


def get_subscription_start_date(subscription):
    if subscription.status == Subscription.STATUS_TRIAL:
        return None
    first_paid = subscription.invoices.filter(
        status=SubscriptionInvoice.STATUS_PAID,
    ).order_by('period_start', 'paid_at').first()
    if first_paid:
        return _as_date(first_paid.period_start)
    initial = _get_prorata_initial_invoice(subscription)
    if initial:
        return _as_date(initial.period_start)
    trial_end = _as_date(subscription.trial_end_date)
    start = _as_date(subscription.start_date)
    if trial_end and start and start <= trial_end:
        return trial_end
    return start


def get_current_billing_period_end(subscription, today=None):
    today = today or timezone.localdate()
    if subscription.status == Subscription.STATUS_TRIAL:
        return subscription.trial_end_date

    subscription_start = _as_date(get_subscription_start_date(subscription))
    prorata_initial = _get_prorata_initial_invoice(subscription)

    if subscription_start and subscription_start > today:
        if prorata_initial:
            return prorata_initial.period_end
        return last_day_of_month(subscription_start)

    month_start = first_day_of_month(today)
    month_end = last_day_of_month(today)

    if subscription_start and subscription_start > month_end:
        return last_day_of_month(subscription_start)

    monthly = _get_monthly_invoice_for_month(subscription, month_start)
    if monthly and (not subscription_start or monthly.period_start >= subscription_start):
        return monthly.period_end

    covering = subscription.invoices.filter(
        period_start__lte=today,
        period_end__gte=today,
    ).exclude(status=SubscriptionInvoice.STATUS_CANCELLED)
    if subscription_start:
        covering = covering.filter(period_start__gte=subscription_start)
    covering = covering.order_by('-period_end').first()
    if covering:
        return covering.period_end

    if prorata_initial and prorata_initial.period_end >= today:
        return prorata_initial.period_end

    if subscription.status == Subscription.STATUS_ACTIVE and subscription_start and today >= subscription_start:
        return month_end

    if subscription_start:
        return last_day_of_month(subscription_start)
    return None


def get_next_billing_period_line(subscription, after_date):
    """Período de faturação completo seguinte ao que termina em after_date."""
    month_start = first_day_of_month(next_month(after_date))
    month_end = last_day_of_month(month_start)
    monthly_invoice = _get_monthly_invoice_for_month(subscription, month_start)
    if monthly_invoice:
        return _period_line_from_invoice(
            monthly_invoice, 'Próximo período de faturação',
        )
    route_count = subscription.contracted_routes or max(
        subscription.organization.route_count, 1,
    )
    monthly_amount = Subscription.calculate_price(route_count)
    days_in_month = calendar.monthrange(month_start.year, month_start.month)[1]
    return {
        'label': 'Próximo período de faturação',
        'start': month_start,
        'end': month_end,
        'is_prorata': False,
        'amount': monthly_amount,
        'monthly_amount': monthly_amount,
        'days_in_month': days_in_month,
        'billable_days': days_in_month,
        'status': None,
    }


def _resolve_next_billing_period(subscription, subscription_end, prorata_initial):
    if not subscription_end:
        return None
    if subscription.status == Subscription.STATUS_TRIAL:
        return None
    if subscription.status == Subscription.STATUS_PENDING:
        if not (
            prorata_initial
            and prorata_initial.status == SubscriptionInvoice.STATUS_PAID
        ):
            return None
    return get_next_billing_period_line(subscription, subscription_end)


def _period_overlaps_month(period_start, period_end, month_start, month_end):
    return period_start <= month_end and period_end >= month_start


def build_subscription_period_context(subscription, today=None):
    """
    Períodos para a página de assinatura.
    Com rotas adicionais proporcionais no mesmo mês, lista cada período.
    Quando só há mensalidade de mês completo, devolve single_period=True.
    """
    today = today or timezone.localdate()
    month_start = first_day_of_month(today)
    month_end = last_day_of_month(today)

    subscription_start = get_subscription_start_date(subscription)
    subscription_end = get_current_billing_period_end(subscription, today)
    period_lines = []

    if subscription.status == Subscription.STATUS_TRIAL:
        tariff = SubscriptionTariff.get()
        trial_end = subscription.trial_end_date
        preview_routes = subscription.contracted_routes or max(
            subscription.organization.route_count, tariff.included_routes,
        )
        preview = compute_contract_prorata_preview(
            subscription, preview_routes, today,
        )
        preview_end = last_day_of_month(today)
        if trial_end:
            contract_note = (
                f'Se contratar hoje ({today.strftime("%d/%m/%Y")}), '
                f'o primeiro pagamento será de {preview["amount"]:.2f} € '
                f'({preview["monthly_amount"]:.2f} € ÷ {preview["days_in_month"]} dias '
                f'× {preview["billable_days"]} dias) até {preview_end.strftime("%d/%m/%Y")}.'
            )
        else:
            contract_note = ''
        return {
            'is_trial': True,
            'trial_start': subscription.start_date,
            'trial_end': trial_end,
            'trial_days_total': tariff.trial_days,
            'contract_note': contract_note,
            'contract_prorata_preview': preview,
            'subscription_start': None,
            'subscription_end': None,
            'period_lines': [],
            'next_billing_period': None,
            'single_period': False,
            'billing_starts_in_future': False,
        }

    cancelled = SubscriptionInvoice.STATUS_CANCELLED
    prorata_initial = _get_prorata_initial_invoice(subscription)

    # Assinatura ainda não começou (ex.: trial termina a 10/07, hoje é Junho)
    if subscription_start and subscription_start > today:
        if prorata_initial:
            period_lines.append(_period_line_from_invoice(
                prorata_initial, 'Primeira mensalidade (proporcional)',
            ))
        else:
            expected = _expected_first_billing_period(subscription)
            if expected:
                period_lines.append(expected)
        single_period = len(period_lines) == 1 and not period_lines[0].get('is_prorata')
        next_billing_period = _resolve_next_billing_period(
            subscription, subscription_end, prorata_initial,
        )
        return {
            'is_trial': False,
            'trial_start': None,
            'trial_end': None,
            'trial_days_total': None,
            'contract_note': '',
            'subscription_start': subscription_start,
            'subscription_end': subscription_end,
            'period_lines': period_lines,
            'next_billing_period': next_billing_period,
            'single_period': single_period,
            'billing_starts_in_future': True,
        }

    month_start = first_day_of_month(today)
    month_end = last_day_of_month(today)
    monthly = None
    if not subscription_start or subscription_start <= month_end:
        monthly = _get_monthly_invoice_for_month(subscription, month_start)

    prorata_routes = subscription.invoices.filter(
        invoice_type=SubscriptionInvoice.TYPE_PRORATA_ROUTE,
        period_start__year=today.year,
        period_start__month=today.month,
    ).exclude(status=cancelled).order_by('period_start')

    in_first_prorata_month = (
        prorata_initial
        and prorata_initial.period_start <= today <= prorata_initial.period_end
    )

    if subscription.status == Subscription.STATUS_PENDING and prorata_initial and not monthly:
        period_lines.append(_period_line_from_invoice(
            prorata_initial, 'Assinatura (proporcional)',
        ))
    elif subscription.status in (
        Subscription.STATUS_ACTIVE,
        Subscription.STATUS_SUSPENDED,
        Subscription.STATUS_PENDING,
    ):
        if monthly and (not subscription_start or monthly.period_start >= subscription_start):
            period_lines.append(_period_line_from_invoice(
                monthly, 'Período da assinatura',
            ))
        elif in_first_prorata_month or (
            prorata_initial
            and not monthly
            and _period_overlaps_month(
                prorata_initial.period_start,
                prorata_initial.period_end,
                month_start,
                month_end,
            )
        ):
            period_lines.append(_period_line_from_invoice(
                prorata_initial, 'Assinatura (proporcional)',
            ))
        elif (
            subscription.status == Subscription.STATUS_ACTIVE
            and subscription_start
            and today >= subscription_start
        ):
            monthly_amount = subscription.monthly_price
            period_lines.append(_period_line_from_prorata(
                'Período da assinatura', monthly_amount, month_start, month_end,
            ))

    for invoice in prorata_routes:
        if not _is_full_month_period(invoice.period_start, invoice.period_end):
            period_lines.append(_period_line_from_invoice(
                invoice, f'Rotas adicionais ({invoice.route_count})',
            ))

    single_period = (
        len(period_lines) == 1
        and not period_lines[0]['is_prorata']
        and _is_full_month_period(period_lines[0]['start'], period_lines[0]['end'])
    )
    next_billing_period = _resolve_next_billing_period(
        subscription, subscription_end, prorata_initial,
    )

    return {
        'is_trial': False,
        'trial_start': None,
        'trial_end': None,
        'trial_days_total': None,
        'contract_note': '',
        'subscription_start': subscription_start,
        'subscription_end': subscription_end,
        'period_lines': period_lines,
        'next_billing_period': next_billing_period,
        'single_period': single_period,
        'billing_starts_in_future': False,
    }
