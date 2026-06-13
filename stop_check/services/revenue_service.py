from decimal import Decimal

from stop_check.models import FinancialAccount, Revenue
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


def sync_revenue_for_comparison(comparison):
    """Cria, actualiza ou remove a receita financeira ligada à produtividade."""
    if comparison.driver_total <= 0:
        Revenue.objects.filter(comparison=comparison).delete()
        return None

    rates = get_comparison_rates(comparison)
    amount = comparison.calculate_revenue(rates).quantize(Decimal('0.01'))
    if amount <= 0:
        Revenue.objects.filter(comparison=comparison).delete()
        return None

    account = get_revenue_account_for_comparison(comparison)
    if comparison.route_id:
        route_label = comparison.route.name
        if comparison.route.delivery_company_id:
            route_label = f'{comparison.route.delivery_company.name} / {route_label}'
    else:
        route_label = comparison.driver.name

    description = f'{route_label} — {comparison.date.strftime("%d/%m/%Y")}'

    revenue, _created = Revenue.objects.update_or_create(
        comparison=comparison,
        defaults={
            'organization': comparison.organization,
            'account': account,
            'route': comparison.route,
            'vehicle': comparison.vehicle,
            'date': comparison.date,
            'description': description,
            'amount': amount,
        },
    )
    return revenue


def sync_revenues_for_company_route(company_route):
    """Re-sincroniza receitas quando o plano de conta da rota muda."""
    for assignment in company_route.assignments.filter(
        comparison__isnull=False,
    ).select_related('comparison'):
        sync_revenue_for_comparison(assignment.comparison)
