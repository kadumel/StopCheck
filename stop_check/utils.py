from calendar import monthrange
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.db.models import Q, Sum

from .models import DailyComparison, Expense, FuelRecord, RateConfig, Revenue


def get_or_create_rate_config(organization):
    config, _ = RateConfig.objects.get_or_create(organization=organization)
    return config


def get_comparison_rates(comparison):
    """Tarifas da rota associada ao comparativo, ou fallback da organização."""
    if comparison.route_id and comparison.route.company_route_id:
        return comparison.route.company_route
    rc = get_or_create_rate_config(comparison.organization)
    return SimpleNamespace(
        price_per_stop=rc.price_per_stop,
        price_per_pudo=rc.price_per_pudo,
        price_per_pickup=rc.price_per_pickup,
        daily_rate=Decimal('0'),
    )


def get_month_range(year, month):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def parse_list_filters(request):
    return {
        'rota': request.GET.get('rota', ''),
        'motorista': request.GET.get('motorista', ''),
        'veiculo': request.GET.get('veiculo', ''),
        'dia': request.GET.get('dia', ''),
        'status': request.GET.get('status', ''),
        'conta': request.GET.get('conta', ''),
    }


def sanitize_day_filter(filter_dia):
    if not filter_dia:
        return ''
    try:
        date.fromisoformat(filter_dia)
        return filter_dia
    except ValueError:
        return ''


def build_filter_params(filters):
    params = {}
    for key in ('rota', 'motorista', 'veiculo', 'dia', 'status', 'conta'):
        if filters.get(key):
            params[key] = filters[key]
    return params


def apply_data_status_filter(queryset, status, *, via_comparison=False):
    """Filtra por estado dos dados (motorista/empresa). via_comparison=True para queryset Route."""
    from .models import DailyComparison

    if not status:
        return queryset

    if via_comparison:
        if status == 'driver_pending':
            return queryset.filter(
                Q(comparison__isnull=True)
                | Q(comparison__driver_data_status=DailyComparison.DATA_PENDING)
            )
        if status == 'company_pending':
            return queryset.filter(
                Q(comparison__isnull=True)
                | Q(comparison__company_data_status=DailyComparison.DATA_PENDING)
            )
        if status == 'any_pending':
            return queryset.filter(
                Q(comparison__isnull=True)
                | Q(comparison__driver_data_status=DailyComparison.DATA_PENDING)
                | Q(comparison__company_data_status=DailyComparison.DATA_PENDING)
            )
        if status == 'complete':
            return queryset.filter(
                comparison__driver_data_status=DailyComparison.DATA_FILLED,
                comparison__company_data_status=DailyComparison.DATA_FILLED,
            )
        return queryset

    if status == 'driver_pending':
        return queryset.filter(driver_data_status=DailyComparison.DATA_PENDING)
    if status == 'company_pending':
        return queryset.filter(company_data_status=DailyComparison.DATA_PENDING)
    if status == 'any_pending':
        return queryset.filter(
            Q(driver_data_status=DailyComparison.DATA_PENDING)
            | Q(company_data_status=DailyComparison.DATA_PENDING)
        )
    if status == 'complete':
        return queryset.filter(
            driver_data_status=DailyComparison.DATA_FILLED,
            company_data_status=DailyComparison.DATA_FILLED,
        )
    return queryset


def apply_route_assignment_filters(queryset, filters):
    if filters['rota']:
        queryset = queryset.filter(company_route_id=filters['rota'])
    if filters['motorista']:
        queryset = queryset.filter(driver_id=filters['motorista'])
    if filters['veiculo']:
        queryset = queryset.filter(vehicle_id=filters['veiculo'])
    dia = sanitize_day_filter(filters['dia'])
    if dia:
        queryset = queryset.filter(date=date.fromisoformat(dia))
    queryset = apply_data_status_filter(
        queryset, filters.get('status', ''), via_comparison=True
    )
    return queryset, {**filters, 'dia': dia}


def apply_fuel_list_filters(queryset, filters):
    if filters.get('motorista'):
        queryset = queryset.filter(driver_id=filters['motorista'])
    if filters.get('veiculo'):
        queryset = queryset.filter(vehicle_id=filters['veiculo'])
    dia = sanitize_day_filter(filters.get('dia', ''))
    if dia:
        queryset = queryset.filter(date=date.fromisoformat(dia))
    return queryset, {**filters, 'dia': dia}


def apply_expense_list_filters(queryset, filters):
    if filters.get('conta'):
        queryset = queryset.filter(account_id=filters['conta'])
    if filters.get('veiculo'):
        queryset = queryset.filter(vehicle_id=filters['veiculo'])
    dia = sanitize_day_filter(filters.get('dia', ''))
    if dia:
        queryset = queryset.filter(date=date.fromisoformat(dia))
    return queryset, {**filters, 'dia': dia}


def apply_revenue_list_filters(queryset, filters):
    if filters.get('conta'):
        queryset = queryset.filter(account_id=filters['conta'])
    if filters.get('veiculo'):
        queryset = queryset.filter(
            Q(comparison__vehicle_id=filters['veiculo'])
            | Q(route__vehicle_id=filters['veiculo'])
            | Q(vehicle_id=filters['veiculo'])
        )
    dia = sanitize_day_filter(filters.get('dia', ''))
    if dia:
        queryset = queryset.filter(date=date.fromisoformat(dia))
    return queryset, {**filters, 'dia': dia}


def apply_comparison_list_filters(queryset, filters):
    if filters['rota']:
        queryset = queryset.filter(route__company_route_id=filters['rota'])
    if filters['motorista']:
        queryset = queryset.filter(driver_id=filters['motorista'])
    if filters['veiculo']:
        queryset = queryset.filter(vehicle_id=filters['veiculo'])
    dia = sanitize_day_filter(filters['dia'])
    if dia:
        queryset = queryset.filter(date=date.fromisoformat(dia))
    queryset = apply_data_status_filter(queryset, filters.get('status', ''))
    return queryset, {**filters, 'dia': dia}


def get_list_filter_choices(organization):
    from .models import CompanyRoute, Driver, FinancialAccount, Vehicle

    return {
        'company_routes': CompanyRoute.objects.filter(
            organization=organization, is_active=True
        ).select_related('delivery_company').order_by('delivery_company__name', 'name'),
        'drivers': Driver.objects.filter(
            organization=organization, is_active=True
        ).order_by('name'),
        'vehicles': Vehicle.objects.filter(
            organization=organization, is_active=True
        ).order_by('plate'),
        'financial_accounts': FinancialAccount.objects.filter(
            organization=organization, account_type=FinancialAccount.TYPE_EXPENSE,
        ).order_by('name'),
        'revenue_accounts': FinancialAccount.objects.filter(
            organization=organization, account_type=FinancialAccount.TYPE_REVENUE,
        ).order_by('name'),
    }


def get_dashboard_stats(organization, year, month):
    start, end = get_month_range(year, month)
    comparisons = DailyComparison.objects.filter(
        organization=organization, date__gte=start, date__lte=end
    ).select_related('route__company_route')

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

    gross_revenue = Revenue.objects.filter(
        organization=organization, date__gte=start, date__lte=end,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    daily_revenue = Decimal('0')
    diff_amount_stops = Decimal('0')
    diff_amount_pudo = Decimal('0')
    diff_amount_pickups = Decimal('0')

    for comp in comparisons:
        rates = get_comparison_rates(comp)
        daily_revenue += rates.daily_rate
        da = comp.calculate_diff_amounts(rates)
        diff_amount_stops += da['stops']
        diff_amount_pudo += da['pudo']
        diff_amount_pickups += da['pickups']

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
        'daily_revenue': daily_revenue,
        'fuel_cost': fuel_cost,
        'fuel_liters': fuel_total,
        'other_expenses': other_expenses,
        'total_expenses': total_expenses,
        'net_profit': net_profit,
        'cost_per_operation': cost_per_operation,
        'discrepancy_count': discrepancy_count,
        'comparisons': comparisons,
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
