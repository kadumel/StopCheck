from decimal import Decimal

from stop_check.models import DailyComparison, FinancialAccount, Revenue
from stop_check.utils import get_comparison_rates


def get_revenue_account_for_comparison(comparison):
    if comparison.route_id and comparison.route.company_route_id:
        account = comparison.route.company_route.revenue_account
        if account:
            return account

    org = comparison.organization
    return (
        org.financial_accounts.filter(
            account_type=FinancialAccount.TYPE_REVENUE, name='Entregas',
        ).first()
        or org.financial_accounts.filter(
            account_type=FinancialAccount.TYPE_REVENUE,
        ).order_by('name').first()
    )


def get_daily_rate_account_for_comparison(comparison):
    if comparison.route_id and comparison.route.company_route_id:
        account = comparison.route.company_route.daily_rate_account
        if account:
            return account
    return get_revenue_account_for_comparison(comparison)


def comparison_has_productivity(comparison):
    return (
        comparison.driver_stops > 0
        or comparison.driver_pudo > 0
        or comparison.driver_pickups > 0
    )


def _comparison_route_label(comparison):
    if comparison.route_id:
        route_label = comparison.route.name
        if comparison.route.delivery_company_id:
            route_label = f'{comparison.route.delivery_company.name} / {route_label}'
        return route_label
    return comparison.driver.name


def _lock_snapshot_daily_rate(comparison, rates):
    """Guarda o valor da diária do cadastro no primeiro lançamento de produtividade."""
    if comparison.snapshot_daily_rate is not None:
        return comparison.snapshot_daily_rate
    rate = (rates.daily_rate or Decimal('0')).quantize(Decimal('0.01'))
    DailyComparison.objects.filter(pk=comparison.pk).update(snapshot_daily_rate=rate)
    return rate


def _sync_revenue_line(
    comparison,
    *,
    kind,
    account,
    amount,
    description_suffix='',
    freeze_after_create=False,
):
    amount = amount.quantize(Decimal('0.01'))
    existing = Revenue.objects.filter(comparison=comparison, revenue_kind=kind).first()

    if amount <= 0:
        Revenue.objects.filter(comparison=comparison, revenue_kind=kind).delete()
        return None

    if existing and freeze_after_create:
        return existing

    date_label = comparison.date.strftime('%d/%m/%Y')
    description = f'{_comparison_route_label(comparison)} — {date_label}{description_suffix}'
    defaults = {
        'organization': comparison.organization,
        'account': account,
        'route': comparison.route,
        'vehicle': comparison.vehicle,
        'date': comparison.date,
        'description': description,
        'amount': amount,
    }

    revenue, _created = Revenue.objects.update_or_create(
        comparison=comparison,
        revenue_kind=kind,
        defaults=defaults,
    )
    return revenue


def sync_revenue_for_comparison(comparison):
    """Cria, actualiza ou remove receitas ligadas ao lançamento de produtividade.

    - Só gera receitas quando existem paragens/PUDO/recolhas do motorista.
    - A diária usa o valor do cadastro da rota no momento do primeiro lançamento
      e não é alterada quando o cadastro da rota muda depois.
    """
    if not comparison_has_productivity(comparison):
        Revenue.objects.filter(comparison=comparison).delete()
        if comparison.snapshot_daily_rate is not None:
            DailyComparison.objects.filter(pk=comparison.pk).update(
                snapshot_daily_rate=None,
            )
        return None

    rates = get_comparison_rates(comparison)
    productivity_amount = (
        comparison.driver_stops * rates.price_per_stop
        + comparison.driver_pudo * rates.price_per_pudo
        + comparison.driver_pickups * rates.price_per_pickup
    )

    productivity_revenue = _sync_revenue_line(
        comparison,
        kind=Revenue.KIND_PRODUCTIVITY,
        account=get_revenue_account_for_comparison(comparison),
        amount=productivity_amount,
    )

    daily_amount = _lock_snapshot_daily_rate(comparison, rates)
    if daily_amount > 0:
        daily_revenue = _sync_revenue_line(
            comparison,
            kind=Revenue.KIND_DAILY_RATE,
            account=get_daily_rate_account_for_comparison(comparison),
            amount=daily_amount,
            description_suffix=' — Diária',
            freeze_after_create=True,
        )
    else:
        Revenue.objects.filter(
            comparison=comparison,
            revenue_kind=Revenue.KIND_DAILY_RATE,
        ).delete()
        daily_revenue = None

    return daily_revenue or productivity_revenue
