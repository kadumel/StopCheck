from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from .models import DailyComparison, Expense, FuelRecord, RateConfig


def get_or_create_rate_config(organization):
    config, _ = RateConfig.objects.get_or_create(organization=organization)
    return config


def get_month_range(year, month):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def get_dashboard_stats(organization, year, month):
    start, end = get_month_range(year, month)
    comparisons = DailyComparison.objects.filter(
        organization=organization, date__gte=start, date__lte=end
    )
    rate_config = get_or_create_rate_config(organization)

    days_with_data = comparisons.values('date').distinct().count()
    totals = comparisons.aggregate(
        total_stops=Sum('driver_stops'),
        total_pudo=Sum('driver_pudo'),
        total_pickups=Sum('driver_pickups'),
        company_stops=Sum('company_stops'),
        company_pudo=Sum('company_pudo'),
        company_pickups=Sum('company_pickups'),
    )

    total_stops = totals['total_stops'] or 0
    total_pudo = totals['total_pudo'] or 0
    total_pickups = totals['total_pickups'] or 0
    total_operations = total_stops + total_pudo + total_pickups

    gross_revenue = Decimal('0')
    for comp in comparisons:
        gross_revenue += comp.calculate_revenue(rate_config)

    fuel_records = FuelRecord.objects.filter(
        organization=organization, date__gte=start, date__lte=end
    )
    fuel_total = fuel_records.aggregate(total=Sum('liters'))['total'] or Decimal('0')

    fuel_cost = Decimal('0')
    for record in fuel_records:
        fuel_cost += record.total_cost

    other_expenses = Expense.objects.filter(
        organization=organization, date__gte=start, date__lte=end
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    total_expenses = fuel_cost + other_expenses
    net_profit = gross_revenue - total_expenses

    cost_per_operation = None
    if total_operations > 0:
        cost_per_operation = fuel_cost / total_operations

    discrepancy_count = sum(1 for c in comparisons if c.has_discrepancy)

    company_stops = totals['company_stops'] or 0
    company_pudo = totals['company_pudo'] or 0
    company_pickups = totals['company_pickups'] or 0

    diff_stops = total_stops - company_stops
    diff_pudo = total_pudo - company_pudo
    diff_pickups = total_pickups - company_pickups

    diff_amount_stops = Decimal(diff_stops) * rate_config.price_per_stop
    diff_amount_pudo = Decimal(diff_pudo) * rate_config.price_per_pudo
    diff_amount_pickups = Decimal(diff_pickups) * rate_config.price_per_pickup
    diff_amount_total = diff_amount_stops + diff_amount_pudo + diff_amount_pickups

    return {
        'days_with_data': days_with_data,
        'avg_stops': round(total_stops / days_with_data, 1) if days_with_data else 0,
        'avg_pudo': round(total_pudo / days_with_data, 1) if days_with_data else 0,
        'avg_pickups': round(total_pickups / days_with_data, 1) if days_with_data else 0,
        'total_stops': total_stops,
        'total_pudo': total_pudo,
        'total_pickups': total_pickups,
        'total_operations': total_operations,
        'gross_revenue': gross_revenue,
        'fuel_cost': fuel_cost,
        'fuel_liters': fuel_total,
        'other_expenses': other_expenses,
        'total_expenses': total_expenses,
        'net_profit': net_profit,
        'cost_per_operation': cost_per_operation,
        'discrepancy_count': discrepancy_count,
        'comparisons': comparisons,
        'rate_config': rate_config,
        'company_totals': {
            'stops': company_stops,
            'pudo': company_pudo,
            'pickups': company_pickups,
        },
        'diff_totals': {
            'stops': diff_stops,
            'pudo': diff_pudo,
            'pickups': diff_pickups,
            'total': diff_stops + diff_pudo + diff_pickups,
        },
        'diff_amounts': {
            'stops': diff_amount_stops,
            'pudo': diff_amount_pudo,
            'pickups': diff_amount_pickups,
            'total': diff_amount_total,
        },
    }
