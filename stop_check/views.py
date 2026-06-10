import csv
import io
from datetime import date

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .decorators import get_home_url_name, manager_required, organization_required
from .forms import (
    DailyComparisonForm,
    DriverForm,
    ExpenseForm,
    FuelRecordForm,
    LoginForm,
    RateConfigForm,
    RegisterForm,
    VehicleForm,
)
from .models import (
    DailyComparison,
    Driver,
    Expense,
    FuelRecord,
    Subscription,
    Vehicle,
)
from .services import stripe_service
from .utils import get_dashboard_stats, get_month_range, get_or_create_rate_config


MONTHS_PT = [
    '', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
    'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
]


def get_period(request):
    today = timezone.localdate()
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))
    return year, month


class CustomLoginView(LoginView):
    template_name = 'stop_check/auth/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse(get_home_url_name(self.request.user))


def register_view(request):
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        return redirect('dashboard')
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Conta criada com sucesso! Bem-vindo ao StopCheck.')
            return redirect('dashboard')
    else:
        form = RegisterForm()
    return render(request, 'stop_check/auth/register.html', {'form': form})


@organization_required
def dashboard(request):
    if request.user.profile.is_driver:
        return redirect('driver_app')
    org = request.user.profile.organization
    year, month = get_period(request)
    stats = get_dashboard_stats(org, year, month)

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    context = {
        'stats': stats,
        'year': year,
        'month': month,
        'month_name': MONTHS_PT[month],
        'prev_month': prev_month,
        'prev_year': prev_year,
        'next_month': next_month,
        'next_year': next_year,
    }
    return render(request, 'stop_check/dashboard/index.html', context)


@organization_required
def comparison_list(request):
    org = request.user.profile.organization
    year, month = get_period(request)
    start, end = get_month_range(year, month)
    comparisons = DailyComparison.objects.filter(
        organization=org, date__gte=start, date__lte=end
    ).select_related('driver', 'vehicle')

    context = {
        'comparisons': comparisons,
        'year': year,
        'month': month,
        'month_name': MONTHS_PT[month],
    }
    return render(request, 'stop_check/comparisons/list.html', context)


@organization_required
def comparison_create(request):
    org = request.user.profile.organization
    if request.method == 'POST':
        form = DailyComparisonForm(request.POST)
        form.fields['driver'].queryset = Driver.objects.filter(organization=org, is_active=True)
        form.fields['vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
        if form.is_valid():
            comp = form.save(commit=False)
            comp.organization = org
            comp.save()
            messages.success(request, 'Comparação registada com sucesso.')
            return redirect('comparison_list')
    else:
        form = DailyComparisonForm(initial={'date': timezone.localdate()})
        form.fields['driver'].queryset = Driver.objects.filter(organization=org, is_active=True)
        form.fields['vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
    return render(request, 'stop_check/comparisons/form.html', {'form': form, 'title': 'Nova Comparação'})


@organization_required
def comparison_edit(request, pk):
    org = request.user.profile.organization
    comp = get_object_or_404(DailyComparison, pk=pk, organization=org)
    if request.method == 'POST':
        form = DailyComparisonForm(request.POST, instance=comp)
        form.fields['driver'].queryset = Driver.objects.filter(organization=org, is_active=True)
        form.fields['vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
        if form.is_valid():
            form.save()
            messages.success(request, 'Comparação atualizada.')
            return redirect('comparison_list')
    else:
        form = DailyComparisonForm(instance=comp)
        form.fields['driver'].queryset = Driver.objects.filter(organization=org, is_active=True)
        form.fields['vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
    return render(request, 'stop_check/comparisons/form.html', {'form': form, 'title': 'Editar Comparação'})


@organization_required
def comparison_delete(request, pk):
    org = request.user.profile.organization
    comp = get_object_or_404(DailyComparison, pk=pk, organization=org)
    if request.method == 'POST':
        comp.delete()
        messages.success(request, 'Comparação eliminada.')
        return redirect('comparison_list')
    return render(request, 'stop_check/comparisons/delete.html', {'object': comp})


@organization_required
def vehicle_list(request):
    org = request.user.profile.organization
    vehicles = Vehicle.objects.filter(organization=org)
    return render(request, 'stop_check/fleet/list.html', {'vehicles': vehicles})


@manager_required
def vehicle_create(request):
    org = request.user.profile.organization
    if request.method == 'POST':
        form = VehicleForm(request.POST)
        if form.is_valid():
            vehicle = form.save(commit=False)
            vehicle.organization = org
            vehicle.save()
            messages.success(request, f'Veículo {vehicle.plate} adicionado.')
            return redirect('vehicle_list')
    else:
        form = VehicleForm()
    return render(request, 'stop_check/fleet/form.html', {'form': form, 'title': 'Novo Veículo'})


@manager_required
def vehicle_edit(request, pk):
    org = request.user.profile.organization
    vehicle = get_object_or_404(Vehicle, pk=pk, organization=org)
    if request.method == 'POST':
        form = VehicleForm(request.POST, instance=vehicle)
        if form.is_valid():
            form.save()
            messages.success(request, 'Veículo atualizado.')
            return redirect('vehicle_list')
    else:
        form = VehicleForm(instance=vehicle)
    return render(request, 'stop_check/fleet/form.html', {'form': form, 'title': 'Editar Veículo'})


@organization_required
def driver_list(request):
    org = request.user.profile.organization
    drivers = Driver.objects.filter(organization=org).select_related('default_vehicle')
    return render(request, 'stop_check/drivers/list.html', {'drivers': drivers})


@manager_required
def driver_create(request):
    org = request.user.profile.organization
    if request.method == 'POST':
        form = DriverForm(request.POST)
        form.organization = org
        form.fields['default_vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
        if form.is_valid():
            driver = form.save()
            messages.success(request, f'Motorista {driver.name} adicionado.')
            return redirect('driver_list')
    else:
        form = DriverForm()
        form.fields['default_vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
    return render(request, 'stop_check/drivers/form.html', {'form': form, 'title': 'Novo Motorista'})


@manager_required
def driver_edit(request, pk):
    org = request.user.profile.organization
    driver = get_object_or_404(Driver, pk=pk, organization=org)
    if request.method == 'POST':
        form = DriverForm(request.POST, instance=driver)
        form.organization = org
        form.fields['default_vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
        if form.is_valid():
            form.save()
            messages.success(request, 'Motorista atualizado.')
            return redirect('driver_list')
    else:
        form = DriverForm(instance=driver)
        if driver.user:
            form.fields['create_account'].initial = True
            form.initial['username'] = driver.user.username
        form.fields['default_vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
    return render(request, 'stop_check/drivers/form.html', {'form': form, 'title': 'Editar Motorista'})


@organization_required
def fuel_list(request):
    org = request.user.profile.organization
    year, month = get_period(request)
    start, end = get_month_range(year, month)
    records = FuelRecord.objects.filter(
        organization=org, date__gte=start, date__lte=end
    ).select_related('vehicle', 'driver')
    total = sum(r.total_cost for r in records)
    return render(request, 'stop_check/fuel/list.html', {
        'records': records, 'total': total,
        'year': year, 'month': month, 'month_name': MONTHS_PT[month],
    })


@organization_required
def fuel_create(request):
    org = request.user.profile.organization
    if request.method == 'POST':
        form = FuelRecordForm(request.POST)
        form.fields['vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
        form.fields['driver'].queryset = Driver.objects.filter(organization=org, is_active=True)
        if form.is_valid():
            record = form.save(commit=False)
            record.organization = org
            record.save()
            messages.success(request, 'Registo de combustível adicionado.')
            return redirect('fuel_list')
    else:
        form = FuelRecordForm(initial={'date': timezone.localdate()})
        form.fields['vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
        form.fields['driver'].queryset = Driver.objects.filter(organization=org, is_active=True)
    return render(request, 'stop_check/fuel/form.html', {'form': form, 'title': 'Novo Abastecimento'})


@organization_required
def expense_list(request):
    org = request.user.profile.organization
    year, month = get_period(request)
    start, end = get_month_range(year, month)
    expenses = Expense.objects.filter(
        organization=org, date__gte=start, date__lte=end
    ).select_related('category', 'vehicle')
    total = sum(e.amount for e in expenses)
    return render(request, 'stop_check/costs/list.html', {
        'expenses': expenses, 'total': total,
        'year': year, 'month': month, 'month_name': MONTHS_PT[month],
    })


@organization_required
def expense_create(request):
    org = request.user.profile.organization
    if request.method == 'POST':
        form = ExpenseForm(request.POST)
        form.fields['vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
        form.fields['category'].queryset = org.expense_categories.all()
        if form.is_valid():
            expense = form.save(commit=False)
            expense.organization = org
            expense.save()
            messages.success(request, 'Despesa registada.')
            return redirect('expense_list')
    else:
        form = ExpenseForm(initial={'date': timezone.localdate()})
        form.fields['vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
        form.fields['category'].queryset = org.expense_categories.all()
    return render(request, 'stop_check/costs/form.html', {'form': form, 'title': 'Nova Despesa'})


@organization_required
def finance_view(request):
    org = request.user.profile.organization
    year, month = get_period(request)
    stats = get_dashboard_stats(org, year, month)
    start, end = get_month_range(year, month)

    fuel_by_vehicle = {}
    for record in FuelRecord.objects.filter(organization=org, date__gte=start, date__lte=end):
        plate = record.vehicle.plate
        fuel_by_vehicle[plate] = fuel_by_vehicle.get(plate, 0) + record.total_cost

    expenses_by_category = {}
    for expense in Expense.objects.filter(organization=org, date__gte=start, date__lte=end):
        cat = expense.category.name if expense.category else 'Sem categoria'
        expenses_by_category[cat] = expenses_by_category.get(cat, 0) + expense.amount

    return render(request, 'stop_check/finance/index.html', {
        'stats': stats,
        'year': year,
        'month': month,
        'month_name': MONTHS_PT[month],
        'fuel_by_vehicle': fuel_by_vehicle,
        'expenses_by_category': expenses_by_category,
    })


@manager_required
def subscription_view(request):
    org = request.user.profile.organization
    if request.GET.get('paid') == '1':
        messages.success(request, 'Pagamento recebido! A sua assinatura está activa.')
    subscription = getattr(org, 'subscription', None)
    vehicles = Vehicle.objects.filter(organization=org, is_active=True)
    vehicle_count = vehicles.count()
    monthly_price = Subscription.calculate_price(vehicle_count)
    rate_config = get_or_create_rate_config(org)

    if request.method == 'POST':
        form = RateConfigForm(request.POST, instance=rate_config)
        if form.is_valid():
            form.save()
            messages.success(request, 'Tarifas atualizadas.')
            return redirect('subscription')
    else:
        form = RateConfigForm(instance=rate_config)

    return render(request, 'stop_check/subscription/index.html', {
        'subscription': subscription,
        'vehicles': vehicles,
        'vehicle_count': vehicle_count,
        'monthly_price': monthly_price,
        'form': form,
        'base_price': Subscription.BASE_PRICE,
        'additional_price': Subscription.ADDITIONAL_VEHICLE_PRICE,
        'stripe_enabled': stripe_service.stripe_enabled(),
    })


@organization_required
def export_excel(request):
    org = request.user.profile.organization
    year, month = get_period(request)
    start, end = get_month_range(year, month)
    stats = get_dashboard_stats(org, year, month)

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    filename = f'stopcheck_{year}_{month:02d}.csv'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')

    writer = csv.writer(response, delimiter=';')
    writer.writerow(['StopCheck - Relatório', MONTHS_PT[month], year])
    writer.writerow([])
    writer.writerow(['Resumo Financeiro'])
    writer.writerow(['Receita Bruta', f'{stats["gross_revenue"]:.2f}'])
    writer.writerow(['Combustível', f'{stats["fuel_cost"]:.2f}'])
    writer.writerow(['Outras Despesas', f'{stats["other_expenses"]:.2f}'])
    writer.writerow(['Total Despesas', f'{stats["total_expenses"]:.2f}'])
    writer.writerow(['Lucro Líquido', f'{stats["net_profit"]:.2f}'])
    writer.writerow([])
    writer.writerow(['Comparações Diárias'])
    writer.writerow([
        'Data', 'Motorista', 'Paradas (Motorista)', 'PUDO (Motorista)', 'Recolhas (Motorista)',
        'Paradas (Empresa)', 'PUDO (Empresa)', 'Recolhas (Empresa)', 'Diferença Total',
    ])
    for comp in stats['comparisons']:
        writer.writerow([
            comp.date.strftime('%d/%m/%Y'),
            comp.driver.name,
            comp.driver_stops, comp.driver_pudo, comp.driver_pickups,
            comp.company_stops, comp.company_pudo, comp.company_pickups,
            comp.diff_total,
        ])

    return response


@organization_required
def export_pdf(request):
    org = request.user.profile.organization
    year, month = get_period(request)
    stats = get_dashboard_stats(org, year, month)
    return render(request, 'stop_check/exports/pdf_report.html', {
        'stats': stats,
        'org': org,
        'year': year,
        'month': month,
        'month_name': MONTHS_PT[month],
    })
