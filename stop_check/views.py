import csv
import io
from datetime import date

from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.views import LoginView
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .decorators import admin_required, get_home_url_name, manager_required, organization_required
from .forms import (
    DailyComparisonForm,
    DriverForm,
    EmailVerificationForm,
    ExpenseForm,
    FinancialAccountForm,
    FuelRecordForm,
    RevenueForm,
    LoginForm,
    RegisterForm,
    SubscriptionContractForm,
    RouteAdditionRequestForm,
    CompanyRouteForm,
    DeliveryCompanyForm,
    ProductionAssignForm,
    RouteForm,
    VehicleForm,
)
from .models import (
    CompanyRoute,
    DailyComparison,
    DeliveryCompany,
    Driver,
    Expense,
    FinancialAccount,
    FuelRecord,
    Revenue,
    Route,
    Subscription,
    SubscriptionInvoice,
    SubscriptionTariff,
    Vehicle,
)
from .services.production_service import (
    analyze_schedule,
    apply_assignments,
    delete_assignments,
    ensure_comparison_for_route,
)
from .services.revenue_service import (
    comparison_has_productivity,
    sync_revenue_for_comparison,
)
from .services.email_service import (
    create_verification,
    resend_verification,
    send_payment_report_notification,
    send_route_addition_request_confirmation,
    send_verification_email,
    verify_code,
)
from .services.registration_service import (
    build_registration_payload,
    create_account_from_payload,
)
from .services.billing_service import (
    at_route_limit,
    base_routes_registered,
    build_subscription_period_context,
    calculate_route_addition_prorata,
    can_request_additional_routes,
    compute_amount_due,
    compute_contract_prorata_preview,
    create_initial_prorata_invoice,
    create_route_addition_request,
    get_current_payable_invoice,
    get_catalog_route_limit,
    get_pending_invoices,
    get_pending_route_request,
    report_invoice_payment,
    route_limit_reached_message,
    sync_subscription_payment_state,
    trial_days_remaining,
)
from .utils import (
    apply_comparison_list_filters,
    apply_expense_list_filters,
    apply_fuel_list_filters,
    apply_revenue_list_filters,
    apply_route_assignment_filters,
    build_filter_params,
    get_comparison_rates,
    get_dashboard_breakdowns,
    get_dashboard_evolution,
    get_dashboard_stats,
    get_list_filter_choices,
    get_month_range,
    parse_list_filters,
)


MONTHS_PT = [
    '', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
    'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
]


def _production_list_url(request):
    """Preserva filtros e mês ao redirecionar para a lista de produção."""
    params = request.GET.urlencode()
    if not params and request.method == 'POST':
        params = request.POST.get('return_query', '')
    if params:
        return f'{reverse("production_list")}?{params}'
    return reverse('production_list')


def _comparison_list_url(request):
    params = request.GET.urlencode()
    if not params and request.method == 'POST':
        params = request.POST.get('return_query', '')
    if params:
        return f'{reverse("comparison_list")}?{params}'
    return reverse('comparison_list')


def _expense_list_url(request):
    params = request.GET.urlencode()
    if not params and request.method == 'POST':
        params = request.POST.get('return_query', '')
    if params:
        return f'{reverse("expense_list")}?{params}'
    return reverse('expense_list')


def _revenue_list_url(request):
    params = request.GET.urlencode()
    if not params and request.method == 'POST':
        params = request.POST.get('return_query', '')
    if params:
        return f'{reverse("revenue_list")}?{params}'
    return reverse('revenue_list')


def _configure_expense_form(form, org):
    form.fields['vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
    form.fields['account'].queryset = org.financial_accounts.filter(
        account_type=FinancialAccount.TYPE_EXPENSE,
    )


def _configure_revenue_form(form, org):
    form.fields['vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
    form.fields['account'].queryset = org.financial_accounts.filter(
        account_type=FinancialAccount.TYPE_REVENUE,
    )


def _configure_company_route_form(form, org):
    form.fields['delivery_company'].queryset = DeliveryCompany.objects.filter(
        organization=org, is_active=True,
    )
    revenue_accounts = org.financial_accounts.filter(
        account_type=FinancialAccount.TYPE_REVENUE,
    )
    form.fields['revenue_account'].queryset = revenue_accounts
    form.fields['daily_rate_account'].queryset = revenue_accounts


def _month_navigation(year, month):
    return {
        'prev_month': month - 1 if month > 1 else 12,
        'prev_year': year if month > 1 else year - 1,
        'next_month': month + 1 if month < 12 else 1,
        'next_year': year if month < 12 else year + 1,
    }


def _production_redirect(request, notice_type='', notice_msg=''):
    url = _production_list_url(request)
    if notice_type and notice_msg:
        sep = '&' if '?' in url else '?'
        url = f'{url}{sep}{urlencode({"notice": notice_type, "notice_msg": notice_msg})}'
    return redirect(url)


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


@never_cache
def offline_view(request):
    return render(request, 'stop_check/offline.html')


@never_cache
@require_http_methods(['GET', 'POST'])
def logout_view(request):
    logout(request)
    return redirect('login')


def register_view(request):
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        return redirect('dashboard')
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email'].lower().strip()
            payload = build_registration_payload(form.cleaned_data)
            verification, code = create_verification(email, payload)
            try:
                send_verification_email(
                    email=email,
                    code=code,
                    organization_name=form.cleaned_data['contracting_company'].name,
                    first_name=form.cleaned_data['first_name'],
                )
            except Exception as exc:
                verification.delete()
                messages.error(request, f'Não foi possível enviar o email de verificação: {exc}')
                return render(request, 'stop_check/auth/register.html', {'form': form})

            request.session['pending_registration_email'] = email
            messages.success(
                request,
                f'Enviámos um código de 6 dígitos para {email}. Verifique a sua caixa de entrada.',
            )
            return redirect('verify_email')
    else:
        form = RegisterForm()
    return render(request, 'stop_check/auth/register.html', {'form': form})


def verify_email_view(request):
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        return redirect('dashboard')

    email = request.session.get('pending_registration_email')
    if not email:
        messages.warning(request, 'Inicie o registo para receber o código de verificação.')
        return redirect('register')

    if request.method == 'POST':
        form = EmailVerificationForm(request.POST)
        if form.is_valid():
            verification, error = verify_code(email, form.cleaned_data['code'])
            if error:
                messages.error(request, error)
            else:
                try:
                    user = create_account_from_payload(verification.payload)
                except ValueError as exc:
                    messages.error(request, str(exc))
                    return redirect('register')

                del request.session['pending_registration_email']
                login(request, user)
                messages.success(request, 'Email confirmado! Bem-vindo ao StopCheck.')
                return redirect('dashboard')
    else:
        form = EmailVerificationForm()

    return render(request, 'stop_check/auth/verify_email.html', {'form': form, 'email': email})


def resend_verification_view(request):
    email = request.session.get('pending_registration_email')
    if not email:
        return redirect('register')

    verification, code, error = resend_verification(email)
    if error:
        messages.error(request, error)
        return redirect('register')

    try:
        send_verification_email(
            email=email,
            code=code,
            organization_name=verification.payload.get('organization_name', ''),
            first_name=verification.payload.get('first_name', ''),
        )
        messages.success(request, 'Novo código enviado para o seu email.')
    except Exception as exc:
        messages.error(request, f'Erro ao reenviar código: {exc}')

    return redirect('verify_email')


@organization_required
def dashboard(request):
    if request.user.profile.is_driver:
        return redirect('driver_app')
    org = request.user.profile.organization
    year, month = get_period(request)
    stats = get_dashboard_stats(org, year, month)
    breakdowns = get_dashboard_breakdowns(org, year, month)
    chart_data = get_dashboard_evolution(org, year, month)

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    context = {
        'stats': stats,
        'by_company': breakdowns['by_company'],
        'by_route': breakdowns['by_route'],
        'chart_data': chart_data,
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
    nav = _month_navigation(year, month)

    filters = parse_list_filters(request)
    comparisons = DailyComparison.objects.filter(
        organization=org, date__gte=start, date__lte=end
    ).select_related(
        'driver', 'vehicle', 'route', 'route__company_route', 'route__delivery_company'
    )
    comparisons, filters = apply_comparison_list_filters(comparisons, filters)
    filter_params = build_filter_params(filters)
    filter_choices = get_list_filter_choices(org)

    context = {
        'comparisons': comparisons,
        'year': year,
        'month': month,
        'month_name': MONTHS_PT[month],
        'filters': filters,
        'filter_params': filter_params,
        'has_filters': any(filters.values()),
        **nav,
        **filter_choices,
    }
    return render(request, 'stop_check/comparisons/list.html', context)


@organization_required
def comparison_sync_finance(request, pk):
    org = request.user.profile.organization
    if request.method != 'POST':
        return redirect(_comparison_list_url(request))

    comp = get_object_or_404(DailyComparison, pk=pk, organization=org)
    if not comparison_has_productivity(comp):
        messages.warning(
            request,
            'Registe produtividade (paragens, PUDO ou recolhas) antes de gerar receitas.',
        )
    else:
        sync_revenue_for_comparison(comp)
        messages.success(request, 'Receitas geradas ou actualizadas no financeiro.')

    return redirect(_comparison_list_url(request))


@organization_required
def comparison_create(request):
    return redirect('production_list')


@organization_required
def comparison_edit(request, pk):
    org = request.user.profile.organization
    comp = get_object_or_404(DailyComparison, pk=pk, organization=org)
    if request.method == 'POST':
        form = DailyComparisonForm(request.POST, instance=comp, organization=org)
        if form.is_valid():
            old_stops = comp.driver_stops
            old_pudo = comp.driver_pudo
            old_pickups = comp.driver_pickups
            comp = form.save()
            driver_changed = (
                comp.driver_stops != old_stops
                or comp.driver_pudo != old_pudo
                or comp.driver_pickups != old_pickups
            )
            if driver_changed:
                from .stop_logging import lock_driver_data_by_admin

                lock_driver_data_by_admin(comp)
            messages.success(request, 'Comparação atualizada.')
            return redirect('comparison_list')
    else:
        form = DailyComparisonForm(instance=comp, organization=org)
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
def comparison_clear(request, pk):
    org = request.user.profile.organization
    comp = get_object_or_404(DailyComparison, pk=pk, organization=org)
    if request.method != 'POST':
        return redirect('comparison_list')

    comp.driver_stops = 0
    comp.driver_pudo = 0
    comp.driver_pickups = 0
    comp.company_stops = 0
    comp.company_pudo = 0
    comp.company_pickups = 0
    comp.driver_data_locked = False
    comp.driver_submitted_at = None
    comp.save()
    if comp.route_id:
        comp.route.stop_events.all().delete()

    return_url = request.POST.get('return_query', '')
    url = reverse('comparison_list')
    if return_url:
        url = f'{url}?{return_url}'
    messages.success(
        request,
        f'Dados de {comp.date.strftime("%d/%m/%Y")} limpos com sucesso.',
    )
    return redirect(url)


@manager_required
def comparison_lock_driver(request, pk):
    org = request.user.profile.organization
    comp = get_object_or_404(DailyComparison, pk=pk, organization=org)
    if request.method != 'POST':
        return redirect('comparison_list')

    from .stop_logging import lock_driver_data_by_admin

    lock_driver_data_by_admin(comp)
    messages.success(
        request,
        f'Edição bloqueada na app para {comp.driver.name} ({comp.date.strftime("%d/%m/%Y")}).',
    )
    return _comparison_driver_lock_redirect(request, comp)


@manager_required
def comparison_unlock_driver(request, pk):
    org = request.user.profile.organization
    comp = get_object_or_404(DailyComparison, pk=pk, organization=org)
    if request.method != 'POST':
        return redirect('comparison_list')

    from .stop_logging import unlock_driver_data

    unlock_driver_data(comp)
    messages.success(
        request,
        f'Edição libertada para {comp.driver.name} ({comp.date.strftime("%d/%m/%Y")}).',
    )
    return _comparison_driver_lock_redirect(request, comp)


def _comparison_driver_lock_redirect(request, comp):
    if request.POST.get('return_to') == 'edit':
        return redirect('comparison_edit', pk=comp.pk)

    return_url = request.POST.get('return_query', '')
    url = reverse('comparison_list')
    if return_url:
        url = f'{url}?{return_url}'
    return redirect(url)


BULK_ENTRY_DRIVER = 'driver'
BULK_ENTRY_COMPANY = 'company'


@organization_required
def comparison_bulk_entry(request):
    org = request.user.profile.organization

    if request.method == 'POST':
        if request.POST.get('launch'):
            ids = request.POST.getlist('selected')
            tipo = request.POST.get('tipo', BULK_ENTRY_DRIVER)
            if tipo not in (BULK_ENTRY_DRIVER, BULK_ENTRY_COMPANY):
                tipo = BULK_ENTRY_DRIVER
            if not ids:
                return_url = request.POST.get('return_query', '')
                url = reverse('comparison_list')
                if return_url:
                    url = f'{url}?{return_url}'
                messages.warning(request, 'Seleccione pelo menos um dia para digitar.')
                return redirect(url)
            params = urlencode({
                'ids': ','.join(ids),
                'tipo': tipo,
                'return': request.POST.get('return_query', ''),
            })
            return redirect(f'{reverse("comparison_bulk_entry")}?{params}')

        ids_raw = request.POST.get('ids', '')
        ids = [int(x) for x in ids_raw.split(',') if x.isdigit()]
        tipo = request.POST.get('tipo', BULK_ENTRY_DRIVER)
        if tipo not in (BULK_ENTRY_DRIVER, BULK_ENTRY_COMPANY):
            tipo = BULK_ENTRY_DRIVER

        from .stop_logging import lock_driver_data_by_admin

        comparisons = DailyComparison.objects.filter(organization=org, pk__in=ids)
        updated = 0
        for comp in comparisons:
            prefix = f'comp_{comp.pk}'
            try:
                stops = max(0, int(request.POST.get(f'{prefix}_stops') or 0))
                pudo = max(0, int(request.POST.get(f'{prefix}_pudo') or 0))
                pickups = max(0, int(request.POST.get(f'{prefix}_pickups') or 0))
            except (TypeError, ValueError):
                continue
            if tipo == BULK_ENTRY_DRIVER:
                comp.driver_stops = stops
                comp.driver_pudo = pudo
                comp.driver_pickups = pickups
                lock_driver_data_by_admin(comp)
            else:
                comp.company_stops = stops
                comp.company_pudo = pudo
                comp.company_pickups = pickups
                comp.save()
            updated += 1

        return_url = request.POST.get('return_query', '')
        url = reverse('comparison_list')
        if return_url:
            url = f'{url}?{return_url}'
        messages.success(request, f'{updated} dia(s) actualizado(s) com sucesso.')
        return redirect(url)

    ids_raw = request.GET.get('ids', '')
    ids = [int(x) for x in ids_raw.split(',') if x.isdigit()]
    tipo = request.GET.get('tipo', BULK_ENTRY_DRIVER)
    if tipo not in (BULK_ENTRY_DRIVER, BULK_ENTRY_COMPANY):
        tipo = BULK_ENTRY_DRIVER
    return_query = request.GET.get('return', '')

    comparisons = list(
        DailyComparison.objects.filter(organization=org, pk__in=ids)
        .select_related('driver', 'vehicle', 'route', 'route__delivery_company')
        .order_by('date', 'pk')
    )
    if not comparisons:
        messages.warning(request, 'Nenhum dia seleccionado para digitação.')
        url = reverse('comparison_list')
        if return_query:
            url = f'{url}?{return_query}'
        return redirect(url)

    context = {
        'comparisons': comparisons,
        'tipo': tipo,
        'ids_csv': ','.join(str(c.pk) for c in comparisons),
        'return_query': return_query,
        'is_driver_mode': tipo == BULK_ENTRY_DRIVER,
        'title': 'Seus dados' if tipo == BULK_ENTRY_DRIVER else 'Dados da empresa',
    }
    return render(request, 'stop_check/comparisons/bulk_entry.html', context)


@manager_required
def route_list(request):
    org = request.user.profile.organization
    companies = DeliveryCompany.objects.filter(organization=org).prefetch_related(
        'company_routes__revenue_account',
        'company_routes__daily_rate_account',
    )
    return render(request, 'stop_check/routes/list.html', {'companies': companies})


@manager_required
def production_list(request):
    org = request.user.profile.organization
    year, month = get_period(request)
    start, end = get_month_range(year, month)
    nav = _month_navigation(year, month)

    filters = parse_list_filters(request)
    assignments = Route.objects.filter(
        organization=org, date__gte=start, date__lte=end
    ).select_related(
        'driver', 'vehicle', 'delivery_company', 'company_route', 'comparison'
    )
    assignments, filters = apply_route_assignment_filters(assignments, filters)
    filter_params = build_filter_params(filters)
    filter_choices = get_list_filter_choices(org)

    context = {
        'assignments': assignments,
        'year': year,
        'month': month,
        'month_name': MONTHS_PT[month],
        'filters': filters,
        'filter_params': filter_params,
        'has_filters': any(filters.values()),
        **nav,
        **filter_choices,
    }
    return render(request, 'stop_check/production/list.html', context)


@manager_required
def delivery_company_create(request):
    org = request.user.profile.organization
    if request.method == 'POST':
        form = DeliveryCompanyForm(request.POST, organization=org)
        if form.is_valid():
            company = form.save(commit=False)
            company.organization = org
            company.save()
            messages.success(request, f'Empresa {company.name} registada.')
            return redirect('route_list')
    else:
        form = DeliveryCompanyForm(organization=org)
    return render(request, 'stop_check/routes/company_form.html', {
        'form': form, 'title': 'Nova Empresa Contratante',
    })


@manager_required
def delivery_company_edit(request, pk):
    org = request.user.profile.organization
    company = get_object_or_404(DeliveryCompany, pk=pk, organization=org)
    if request.method == 'POST':
        form = DeliveryCompanyForm(request.POST, instance=company, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, 'Empresa atualizada.')
            return redirect('route_list')
    else:
        form = DeliveryCompanyForm(instance=company, organization=org)
    return render(request, 'stop_check/routes/company_form.html', {
        'form': form, 'title': 'Editar Empresa Contratante',
    })


@manager_required
def delivery_company_delete(request, pk):
    org = request.user.profile.organization
    company = get_object_or_404(DeliveryCompany, pk=pk, organization=org)
    blockers = company.get_delete_blockers()

    if blockers:
        if request.method == 'POST':
            messages.error(
                request,
                'Não é possível eliminar: a empresa está referenciada noutros registos.',
            )
            return redirect('route_list')
        return render(request, 'stop_check/routes/delete_company.html', {
            'object': company,
            'blockers': blockers,
        })

    if request.method == 'POST':
        name = company.name
        company.delete()
        messages.success(request, f'Empresa {name} eliminada.')
        return redirect('route_list')

    return render(request, 'stop_check/routes/delete_company.html', {
        'object': company,
        'blockers': [],
    })


@manager_required
def company_route_create(request):
    org = request.user.profile.organization
    subscription = getattr(org, 'subscription', None)
    if subscription is None:
        subscription = Subscription.objects.create(organization=org)
    subscription.ensure_trial_end_date()

    if at_route_limit(subscription, org):
        messages.warning(request, route_limit_reached_message(subscription))
        return redirect('subscription')

    company_pk = request.GET.get('empresa')
    if request.method == 'POST':
        form = CompanyRouteForm(request.POST)
        _configure_company_route_form(form, org)
        if form.is_valid():
            if at_route_limit(subscription, org):
                messages.warning(request, route_limit_reached_message(subscription))
                return redirect('subscription')
            route = form.save(commit=False)
            route.organization = org
            route.save()
            messages.success(request, f'Rota {route.name} registada.')
            return redirect('route_list')
    else:
        initial = {}
        if company_pk:
            initial['delivery_company'] = company_pk
        form = CompanyRouteForm(initial=initial)
        _configure_company_route_form(form, org)

    slots = subscription.available_route_slots
    return render(request, 'stop_check/routes/company_route_form.html', {
        'form': form,
        'title': 'Nova Rota da Empresa',
        'available_route_slots': slots,
    })


@manager_required
def company_route_edit(request, pk):
    org = request.user.profile.organization
    company_route = get_object_or_404(CompanyRoute, pk=pk, organization=org)
    if request.method == 'POST':
        form = CompanyRouteForm(request.POST, instance=company_route)
        _configure_company_route_form(form, org)
        if form.is_valid():
            form.save()
            for assignment in company_route.assignments.all():
                assignment.sync_from_company_route()
                assignment.save()
            messages.success(request, 'Rota da empresa atualizada.')
            return redirect('route_list')
    else:
        form = CompanyRouteForm(instance=company_route)
        _configure_company_route_form(form, org)
    return render(request, 'stop_check/routes/company_route_form.html', {
        'form': form, 'title': 'Editar Rota da Empresa',
    })


@manager_required
def company_route_delete(request, pk):
    org = request.user.profile.organization
    company_route = get_object_or_404(CompanyRoute, pk=pk, organization=org)
    blockers = company_route.get_delete_blockers()

    if blockers:
        if request.method == 'POST':
            messages.error(
                request,
                'Não é possível eliminar: a rota está referenciada em produção.',
            )
            return redirect('route_list')
        return render(request, 'stop_check/routes/delete_company_route.html', {
            'object': company_route,
            'blockers': blockers,
        })

    if request.method == 'POST':
        label = str(company_route)
        company_route.delete()
        messages.success(request, f'Rota {label} eliminada.')
        return redirect('route_list')

    return render(request, 'stop_check/routes/delete_company_route.html', {
        'object': company_route,
        'blockers': [],
    })


def _route_create_redirect(notice_type='', notice_msg='', keep_continue=False):
    params = {}
    if notice_type and notice_msg:
        params['notice'] = notice_type
        params['notice_msg'] = notice_msg
    if keep_continue:
        params['continuar'] = '1'
    url = reverse('route_create')
    if params:
        url = f'{url}?{urlencode(params)}'
    return redirect(url)


@manager_required
def route_create(request):
    org = request.user.profile.organization
    analysis = None
    show_confirm = False

    if request.method == 'POST':
        form = ProductionAssignForm(request.POST, organization=org)
        if form.is_valid():
            company_route = form.cleaned_data['company_route']
            dates = form.get_target_dates()
            analysis = analyze_schedule(org, company_route, dates)
            mode = form.cleaned_data['schedule_mode']
            confirmed = form.cleaned_data.get('confirm_step')

            if mode == ProductionAssignForm.SCHEDULE_DAY and analysis['protected']:
                form.add_error(
                    'date',
                    'Já existe produção registada neste dia (stops, PUDO ou recolhas). '
                    'Não pode ser substituído.',
                )
            elif analysis['replaceable'] and not confirmed:
                show_confirm = True
            else:
                replace = form.cleaned_data.get('replace_existing', False)
                continue_adding = form.cleaned_data.get('continue_adding', False)
                created, replaced, skipped = apply_assignments(
                    org,
                    company_route,
                    form.cleaned_data['driver'],
                    form.cleaned_data['vehicle'],
                    form.cleaned_data.get('notes', ''),
                    form.cleaned_data.get('is_active', True),
                    analysis,
                    replace,
                )
                if created == replaced == 0 and skipped and not analysis['replaceable']:
                    msg = 'Nenhuma atribuição criada. Todos os dias têm dados registados.'
                    if continue_adding:
                        return _route_create_redirect('warning', msg)
                    return _production_redirect(request, 'warning', msg)
                elif created == replaced == 0 and analysis['replaceable'] and not replace:
                    msg = 'Nenhuma alteração. Marque a opção de substituir para atualizar dias existentes sem dados.'
                    if continue_adding:
                        return _route_create_redirect('warning', msg)
                    return _production_redirect(request, 'warning', msg)
                else:
                    parts = []
                    if created:
                        parts.append(f'{created} criada(s)')
                    if replaced:
                        parts.append(f'{replaced} substituída(s)')
                    if skipped:
                        parts.append(f'{skipped} ignorada(s) com dados')
                    msg = f'Produção: {", ".join(parts)}.'
                    if continue_adding:
                        return _route_create_redirect('success', msg, keep_continue=True)
                    return _production_redirect(request, 'success', msg)
    else:
        initial = {'date': timezone.localdate()}
        if request.GET.get('continuar'):
            initial['continue_adding'] = True
        route_pk = request.GET.get('rota')
        if route_pk:
            initial['company_route'] = route_pk
        form = ProductionAssignForm(initial=initial, organization=org)

    return render(request, 'stop_check/production/form.html', {
        'form': form,
        'title': 'Atribuir Rota a Executar',
        'analysis': analysis,
        'show_confirm': show_confirm,
    })


@manager_required
def route_edit(request, pk):
    org = request.user.profile.organization
    route = get_object_or_404(Route, pk=pk, organization=org)
    if request.method == 'POST':
        form = RouteForm(request.POST, instance=route, organization=org)
        form.fields['driver'].queryset = Driver.objects.filter(organization=org, is_active=True)
        form.fields['vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
        if form.is_valid():
            route = form.save()
            ensure_comparison_for_route(route)
            return _production_redirect(request, 'success', 'Atribuição atualizada.')
    else:
        form = RouteForm(instance=route, organization=org)
        form.fields['driver'].queryset = Driver.objects.filter(organization=org, is_active=True)
        form.fields['vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
    return render(request, 'stop_check/production/edit.html', {
        'form': form, 'title': 'Editar Atribuição de Rota',
    })


@manager_required
def route_delete(request, pk):
    org = request.user.profile.organization
    route = get_object_or_404(Route, pk=pk, organization=org)
    if not route.can_be_deleted:
        return _production_redirect(
            request, 'error',
            'Não é possível eliminar: já existem dados de produção registados neste dia.',
        )
    if request.method == 'POST':
        route.delete()
        return _production_redirect(request, 'success', 'Atribuição eliminada.')
    return render(request, 'stop_check/production/delete.html', {
        'object': route,
        'return_query': request.GET.urlencode(),
    })


@manager_required
def route_bulk_delete(request):
    org = request.user.profile.organization
    if request.method != 'POST':
        return redirect('production_list')

    ids = request.POST.getlist('selected')
    if not ids:
        return _production_redirect(request, 'warning', 'Nenhuma atribuição seleccionada.')

    deleted, blocked = delete_assignments(org, ids)
    if deleted and blocked:
        labels = ', '.join(r.date.strftime('%d/%m/%Y') for r in blocked[:3])
        extra = f' (+{len(blocked) - 3})' if len(blocked) > 3 else ''
        return _production_redirect(
            request, 'warning',
            f'{deleted} eliminada(s). {len(blocked)} não eliminada(s) com dados: {labels}{extra}.',
        )
    if deleted:
        return _production_redirect(
            request, 'success',
            f'{deleted} atribuição(ões) eliminada(s).',
        )
    if blocked:
        return _production_redirect(
            request, 'error',
            f'{len(blocked)} atribuição(ões) não eliminada(s) por terem dados de produção.',
        )
    return _production_redirect(request, 'warning', 'Nenhuma atribuição encontrada.')


@organization_required
def vehicle_list(request):
    org = request.user.profile.organization
    filter_placa = request.GET.get('placa', '').strip()
    vehicles = Vehicle.objects.filter(organization=org).order_by('plate')
    if filter_placa:
        vehicles = vehicles.filter(plate__icontains=filter_placa)
    return render(request, 'stop_check/fleet/list.html', {
        'vehicles': vehicles,
        'filter_placa': filter_placa,
        'has_filter': bool(filter_placa),
    })


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


@manager_required
def vehicle_delete(request, pk):
    org = request.user.profile.organization
    vehicle = get_object_or_404(Vehicle, pk=pk, organization=org)
    return_placa = request.GET.get('placa', '') or request.POST.get('return_placa', '')

    def _redirect_list():
        url = reverse('vehicle_list')
        if return_placa:
            url = f'{url}?{urlencode({"placa": return_placa})}'
        return redirect(url)

    blockers = vehicle.get_delete_blockers()
    if blockers:
        if request.method == 'POST':
            messages.error(
                request,
                'Não é possível eliminar: o veículo está referenciado noutros registos.',
            )
            return _redirect_list()
        return render(request, 'stop_check/fleet/delete.html', {
            'object': vehicle,
            'blockers': blockers,
            'return_placa': return_placa,
        })

    if request.method == 'POST':
        plate = vehicle.plate
        vehicle.delete()
        messages.success(request, f'Veículo {plate} eliminado.')
        return _redirect_list()

    return render(request, 'stop_check/fleet/delete.html', {
        'object': vehicle,
        'blockers': [],
        'return_placa': return_placa,
    })


@organization_required
def driver_list(request):
    org = request.user.profile.organization
    filter_q = request.GET.get('q', '').strip()
    drivers = Driver.objects.filter(organization=org).order_by('name')
    if filter_q:
        drivers = drivers.filter(
            Q(name__icontains=filter_q) | Q(nif__icontains=filter_q)
        )
    return render(request, 'stop_check/drivers/list.html', {
        'drivers': drivers,
        'filter_q': filter_q,
        'has_filter': bool(filter_q),
    })


@manager_required
def driver_create(request):
    org = request.user.profile.organization
    if request.method == 'POST':
        form = DriverForm(request.POST)
        form.organization = org
        if form.is_valid():
            driver = form.save()
            messages.success(request, f'Motorista {driver.name} adicionado.')
            return redirect('driver_list')
    else:
        form = DriverForm()
    return render(request, 'stop_check/drivers/form.html', {'form': form, 'title': 'Novo Motorista'})


@manager_required
def driver_edit(request, pk):
    org = request.user.profile.organization
    driver = get_object_or_404(Driver, pk=pk, organization=org)
    if request.method == 'POST':
        form = DriverForm(request.POST, instance=driver)
        form.organization = org
        if form.is_valid():
            form.save()
            messages.success(request, 'Motorista atualizado.')
            return redirect('driver_list')
    else:
        form = DriverForm(instance=driver)
        if driver.user:
            form.fields['create_account'].initial = True
    return render(request, 'stop_check/drivers/form.html', {'form': form, 'title': 'Editar Motorista'})


@manager_required
def driver_delete(request, pk):
    org = request.user.profile.organization
    driver = get_object_or_404(Driver, pk=pk, organization=org)
    return_q = request.GET.get('q', '') or request.POST.get('return_q', '')

    def _redirect_list():
        url = reverse('driver_list')
        if return_q:
            url = f'{url}?{urlencode({"q": return_q})}'
        return redirect(url)

    blockers = driver.get_delete_blockers()
    if blockers:
        if request.method == 'POST':
            messages.error(
                request,
                'Não é possível eliminar: o motorista está referenciado noutros registos.',
            )
            return _redirect_list()
        return render(request, 'stop_check/drivers/delete.html', {
            'object': driver,
            'blockers': blockers,
            'return_q': return_q,
        })

    if request.method == 'POST':
        name = driver.name
        user = driver.user
        driver.delete()
        if user:
            user.delete()
        messages.success(request, f'Motorista {name} eliminado.')
        return _redirect_list()

    return render(request, 'stop_check/drivers/delete.html', {
        'object': driver,
        'blockers': [],
        'return_q': return_q,
    })


@organization_required
def fuel_list(request):
    org = request.user.profile.organization
    year, month = get_period(request)
    start, end = get_month_range(year, month)
    nav = _month_navigation(year, month)

    filters = parse_list_filters(request)
    records = FuelRecord.objects.filter(
        organization=org, date__gte=start, date__lte=end
    ).select_related('vehicle', 'driver')
    records, filters = apply_fuel_list_filters(records, filters)
    filter_params = build_filter_params(filters)
    filter_choices = get_list_filter_choices(org)
    total = sum(r.total_cost for r in records)

    return render(request, 'stop_check/fuel/list.html', {
        'records': records,
        'total': total,
        'year': year,
        'month': month,
        'month_name': MONTHS_PT[month],
        'filters': filters,
        'filter_params': filter_params,
        'has_filters': any([filters.get('motorista'), filters.get('veiculo'), filters.get('dia')]),
        **nav,
        **filter_choices,
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


@admin_required
def fuel_edit(request, pk):
    org = request.user.profile.organization
    record = get_object_or_404(FuelRecord, pk=pk, organization=org)
    if request.method == 'POST':
        form = FuelRecordForm(request.POST, instance=record)
        form.fields['vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
        form.fields['driver'].queryset = Driver.objects.filter(organization=org, is_active=True)
        if form.is_valid():
            form.save()
            messages.success(request, 'Registo de combustível atualizado.')
            return redirect('fuel_list')
    else:
        form = FuelRecordForm(instance=record)
        form.fields['vehicle'].queryset = Vehicle.objects.filter(organization=org, is_active=True)
        form.fields['driver'].queryset = Driver.objects.filter(organization=org, is_active=True)
    return render(request, 'stop_check/fuel/form.html', {'form': form, 'title': 'Editar Abastecimento'})


@admin_required
def fuel_delete(request, pk):
    org = request.user.profile.organization
    record = get_object_or_404(FuelRecord, pk=pk, organization=org)
    if request.method == 'POST':
        record.delete()
        messages.success(request, 'Registo de combustível eliminado.')
        return redirect('fuel_list')
    return render(request, 'stop_check/fuel/delete.html', {'object': record})


@organization_required
def expense_list(request):
    org = request.user.profile.organization
    year, month = get_period(request)
    start, end = get_month_range(year, month)
    nav = _month_navigation(year, month)

    filters = parse_list_filters(request)
    expenses = Expense.objects.filter(
        organization=org, date__gte=start, date__lte=end
    ).select_related('account', 'vehicle')
    expenses, filters = apply_expense_list_filters(expenses, filters)
    filter_params = build_filter_params(filters)
    filter_choices = get_list_filter_choices(org)
    total = sum(e.amount for e in expenses)

    return render(request, 'stop_check/costs/list.html', {
        'expenses': expenses,
        'total': total,
        'year': year,
        'month': month,
        'month_name': MONTHS_PT[month],
        'filters': filters,
        'filter_params': filter_params,
        'has_filters': any([filters.get('conta'), filters.get('veiculo'), filters.get('dia')]),
        **nav,
        **filter_choices,
    })


@organization_required
def expense_bulk_delete(request):
    org = request.user.profile.organization
    if request.method != 'POST':
        return redirect(_expense_list_url(request))

    ids = request.POST.getlist('selected')
    if not ids:
        messages.warning(request, 'Nenhuma despesa seleccionada.')
        return redirect(_expense_list_url(request))

    deleted = Expense.objects.filter(
        organization=org,
        pk__in=ids,
    ).count()
    Expense.objects.filter(organization=org, pk__in=ids).delete()
    messages.success(request, f'{deleted} despesa(s) eliminada(s).')
    return redirect(_expense_list_url(request))


@organization_required
def expense_create(request):
    org = request.user.profile.organization
    if request.method == 'POST':
        form = ExpenseForm(request.POST)
        _configure_expense_form(form, org)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.organization = org
            expense.save()
            messages.success(request, 'Despesa registada.')
            return redirect(_expense_list_url(request))
    else:
        form = ExpenseForm(initial={'date': timezone.localdate()})
        _configure_expense_form(form, org)
    return render(request, 'stop_check/costs/form.html', {
        'form': form,
        'title': 'Nova Despesa',
        'return_url': _expense_list_url(request),
        'return_query': request.GET.urlencode(),
    })


@organization_required
def expense_edit(request, pk):
    org = request.user.profile.organization
    expense = get_object_or_404(Expense, pk=pk, organization=org)
    if request.method == 'POST':
        form = ExpenseForm(request.POST, instance=expense)
        _configure_expense_form(form, org)
        if form.is_valid():
            form.save()
            messages.success(request, 'Despesa actualizada.')
            return redirect(_expense_list_url(request))
    else:
        form = ExpenseForm(instance=expense)
        _configure_expense_form(form, org)
    return render(request, 'stop_check/costs/form.html', {
        'form': form,
        'title': 'Editar Despesa',
        'return_url': _expense_list_url(request),
        'return_query': request.GET.urlencode(),
    })


@organization_required
def expense_delete(request, pk):
    org = request.user.profile.organization
    expense = get_object_or_404(Expense, pk=pk, organization=org)
    return_url = _expense_list_url(request)
    if request.method == 'POST':
        expense.delete()
        messages.success(request, 'Despesa eliminada.')
        return redirect(return_url)
    return render(request, 'stop_check/costs/delete.html', {
        'object': expense,
        'return_url': return_url,
    })


@manager_required
def financial_account_list(request):
    org = request.user.profile.organization
    filter_type = request.GET.get('tipo', '').strip()
    accounts = org.financial_accounts.order_by('account_type', 'name')
    if filter_type in (FinancialAccount.TYPE_EXPENSE, FinancialAccount.TYPE_REVENUE):
        accounts = accounts.filter(account_type=filter_type)
    return render(request, 'stop_check/financial_accounts/list.html', {
        'accounts': accounts,
        'filter_type': filter_type,
        'has_filter': bool(filter_type),
    })


@manager_required
def financial_account_create(request):
    org = request.user.profile.organization
    if request.method == 'POST':
        form = FinancialAccountForm(request.POST)
        if form.is_valid():
            account = form.save(commit=False)
            account.organization = org
            account.save()
            messages.success(request, f'Plano de conta «{account.name}» criado.')
            return redirect('financial_account_list')
    else:
        form = FinancialAccountForm()
    return render(request, 'stop_check/financial_accounts/form.html', {
        'form': form, 'title': 'Novo Plano de Conta',
    })


@manager_required
def financial_account_edit(request, pk):
    org = request.user.profile.organization
    account = get_object_or_404(FinancialAccount, pk=pk, organization=org)
    if request.method == 'POST':
        form = FinancialAccountForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            messages.success(request, f'Plano de conta «{account.name}» actualizado.')
            return redirect('financial_account_list')
    else:
        form = FinancialAccountForm(instance=account)
    return render(request, 'stop_check/financial_accounts/form.html', {
        'form': form, 'title': 'Editar Plano de Conta',
    })


@manager_required
def financial_account_delete(request, pk):
    org = request.user.profile.organization
    account = get_object_or_404(FinancialAccount, pk=pk, organization=org)
    return_tipo = request.GET.get('tipo', '') or request.POST.get('return_tipo', '')

    def _redirect_list():
        url = reverse('financial_account_list')
        if return_tipo:
            url = f'{url}?{urlencode({"tipo": return_tipo})}'
        return redirect(url)

    blockers = account.get_delete_blockers()
    if blockers:
        if request.method == 'POST':
            messages.error(
                request,
                'Não é possível eliminar: o plano de conta está referenciado noutros registos.',
            )
            return _redirect_list()
        return render(request, 'stop_check/financial_accounts/delete.html', {
            'object': account,
            'blockers': blockers,
            'return_tipo': return_tipo,
        })

    if request.method == 'POST':
        name = account.name
        account.delete()
        messages.success(request, f'Plano de conta «{name}» eliminado.')
        return _redirect_list()

    return render(request, 'stop_check/financial_accounts/delete.html', {
        'object': account,
        'blockers': [],
        'return_tipo': return_tipo,
    })


@organization_required
def revenue_list(request):
    org = request.user.profile.organization
    year, month = get_period(request)
    start, end = get_month_range(year, month)
    nav = _month_navigation(year, month)

    filters = parse_list_filters(request)
    revenues = Revenue.objects.filter(
        organization=org, date__gte=start, date__lte=end,
    ).select_related(
        'account', 'route', 'vehicle', 'comparison', 'comparison__vehicle',
    ).order_by('date', 'pk')
    revenues, filters = apply_revenue_list_filters(revenues, filters)
    filter_params = build_filter_params(filters)
    filter_choices = get_list_filter_choices(org)
    total = sum(r.amount for r in revenues)

    return render(request, 'stop_check/finance/revenue_list.html', {
        'revenues': revenues,
        'total': total,
        'year': year,
        'month': month,
        'month_name': MONTHS_PT[month],
        'filters': filters,
        'filter_params': filter_params,
        'has_filters': any([filters.get('conta'), filters.get('veiculo'), filters.get('dia')]),
        **nav,
        **filter_choices,
    })


@organization_required
def revenue_bulk_delete(request):
    org = request.user.profile.organization
    if request.method != 'POST':
        return redirect(_revenue_list_url(request))

    ids = request.POST.getlist('selected')
    if not ids:
        messages.warning(request, 'Nenhuma receita seleccionada.')
        return redirect(_revenue_list_url(request))

    deleted = Revenue.objects.filter(
        organization=org,
        pk__in=ids,
    ).count()
    Revenue.objects.filter(organization=org, pk__in=ids).delete()
    messages.success(request, f'{deleted} receita(s) eliminada(s).')
    return redirect(_revenue_list_url(request))


@organization_required
def revenue_create(request):
    org = request.user.profile.organization
    if request.method == 'POST':
        form = RevenueForm(request.POST)
        _configure_revenue_form(form, org)
        if form.is_valid():
            revenue = form.save(commit=False)
            revenue.organization = org
            revenue.save()
            messages.success(request, 'Receita registada.')
            return redirect(_revenue_list_url(request))
    else:
        form = RevenueForm(initial={'date': timezone.localdate()})
        _configure_revenue_form(form, org)
    return render(request, 'stop_check/finance/revenue_form.html', {
        'form': form,
        'title': 'Nova Receita',
        'return_url': _revenue_list_url(request),
        'return_query': request.GET.urlencode(),
    })


@organization_required
def revenue_edit(request, pk):
    org = request.user.profile.organization
    revenue = get_object_or_404(Revenue, pk=pk, organization=org)
    if revenue.comparison_id:
        messages.info(request, 'Esta receita foi gerada pela produtividade. Edite os dados na comparação.')
        return redirect(
            f'{reverse("comparison_edit", args=[revenue.comparison_id])}?{request.GET.urlencode()}'
        )
    if request.method == 'POST':
        form = RevenueForm(request.POST, instance=revenue)
        _configure_revenue_form(form, org)
        if form.is_valid():
            form.save()
            messages.success(request, 'Receita actualizada.')
            return redirect(_revenue_list_url(request))
    else:
        form = RevenueForm(instance=revenue)
        _configure_revenue_form(form, org)
    return render(request, 'stop_check/finance/revenue_form.html', {
        'form': form,
        'title': 'Editar Receita',
        'return_url': _revenue_list_url(request),
        'return_query': request.GET.urlencode(),
    })


@organization_required
def revenue_delete(request, pk):
    org = request.user.profile.organization
    revenue = get_object_or_404(Revenue, pk=pk, organization=org)
    return_url = _revenue_list_url(request)
    if request.method == 'POST':
        revenue.delete()
        messages.success(request, 'Receita eliminada.')
        return redirect(return_url)
    return render(request, 'stop_check/finance/revenue_delete.html', {
        'object': revenue,
        'return_url': return_url,
        'is_manual': revenue.is_manual,
    })


@organization_required
def finance_view(request):
    org = request.user.profile.organization
    year, month = get_period(request)
    stats = get_dashboard_stats(org, year, month)
    start, end = get_month_range(year, month)
    today = timezone.localdate()

    fuel_by_vehicle = {}
    for record in FuelRecord.objects.filter(organization=org, date__gte=start, date__lte=end):
        plate = record.vehicle.plate
        fuel_by_vehicle[plate] = fuel_by_vehicle.get(plate, 0) + record.total_cost

    expenses_by_account = {}
    for expense in Expense.objects.filter(organization=org, date__gte=start, date__lte=end):
        label = expense.account.name if expense.account else 'Sem plano de conta'
        expenses_by_account[label] = expenses_by_account.get(label, 0) + expense.amount

    return render(request, 'stop_check/finance/index.html', {
        'stats': stats,
        'year': year,
        'month': month,
        'month_name': MONTHS_PT[month],
        'month_choices': [(i, MONTHS_PT[i]) for i in range(1, 13)],
        'year_choices': range(today.year - 2, today.year + 2),
        'fuel_by_vehicle': fuel_by_vehicle,
        'expenses_by_account': expenses_by_account,
        **_month_navigation(year, month),
    })


@manager_required
def subscription_view(request):
    org = request.user.profile.organization
    subscription = getattr(org, 'subscription', None)
    if subscription is None:
        subscription = Subscription.objects.create(organization=org)
    subscription.ensure_trial_end_date()
    sync_subscription_payment_state(subscription)

    tariff = SubscriptionTariff.get()
    contract_form = SubscriptionContractForm(tariff=tariff)
    route_request_form = RouteAdditionRequestForm()
    today = timezone.localdate()

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'contract' and subscription.status in (
            Subscription.STATUS_TRIAL, Subscription.STATUS_CANCELLED,
        ):
            contract_form = SubscriptionContractForm(request.POST, tariff=tariff)
            if contract_form.is_valid():
                route_count = contract_form.cleaned_data['contracted_routes']
                subscription.contracted_routes = route_count
                subscription.payment_method = contract_form.cleaned_data['payment_method']
                subscription.status = Subscription.STATUS_PENDING
                subscription.payment_reported_at = None
                subscription.save()
                create_initial_prorata_invoice(subscription, route_count, today)
                messages.success(
                    request,
                    'Pedido de contratação enviado. Efectue o pagamento proporcional e informe-nos quando concluir.',
                )
                return redirect('subscription')

        elif action == 'request_routes' and subscription.status == Subscription.STATUS_ACTIVE:
            if not can_request_additional_routes(subscription, org, tariff):
                if not base_routes_registered(org, tariff):
                    messages.error(
                        request,
                        f'Registre as {tariff.included_routes} rotas do plano base no catálogo '
                        f'antes de contratar rotas adicionais.',
                    )
                else:
                    messages.error(
                        request,
                        'Ainda tem vagas no plano actual. Registe as rotas disponíveis primeiro.',
                    )
                return redirect('subscription')
            route_request_form = RouteAdditionRequestForm(request.POST)
            if route_request_form.is_valid():
                additional = route_request_form.cleaned_data['additional_routes']
                try:
                    route_request = create_route_addition_request(
                        subscription, additional, today,
                    )
                    send_route_addition_request_confirmation(route_request)
                    messages.success(
                        request,
                        f'Pedido de {additional} rota(s) adicional(is) registado. '
                        f'Enviámos um email com os dados de pagamento. '
                        f'Após confirmação, poderá registar as rotas no catálogo.',
                    )
                except ValueError as exc:
                    messages.error(request, str(exc))
            return redirect('subscription')

        elif action == 'report_payment':
            invoice_id = request.POST.get('invoice_id')
            invoice = None
            if invoice_id:
                invoice = get_object_or_404(
                    SubscriptionInvoice,
                    pk=invoice_id,
                    subscription=subscription,
                )
            else:
                invoice = get_current_payable_invoice(subscription)

            if not invoice or not invoice.is_payable:
                messages.info(request, 'Não existe cobrança pendente para informar.')
            elif invoice.payment_reported:
                messages.info(request, 'O pagamento já foi informado. Aguarde a nossa confirmação.')
            else:
                try:
                    send_payment_report_notification(subscription, invoice=invoice)
                    report_invoice_payment(invoice)
                    messages.success(
                        request,
                        'Obrigado! Informámos a nossa equipa. O acesso será activado após confirmação do pagamento.',
                    )
                except ValueError as exc:
                    messages.error(request, str(exc))
            return redirect('subscription')

    routes = CompanyRoute.objects.filter(
        organization=org, is_active=True, pending_payment=False,
    ).select_related('delivery_company').order_by('delivery_company__name', 'name')
    route_count = org.route_count
    preview_routes = subscription.contracted_routes or max(route_count, tariff.included_routes)
    monthly_price = Subscription.calculate_price(preview_routes)
    pending_invoices = get_pending_invoices(subscription)
    current_invoice = pending_invoices.first()
    pending_route_request = get_pending_route_request(subscription)
    available_slots = subscription.available_route_slots
    route_addition_preview = None
    route_addition_preview_details = None
    can_add_routes = can_request_additional_routes(subscription, org, tariff)
    if can_add_routes:
        period_end = Subscription.month_end(today)
        unit = Subscription.calculate_additional_route_price()
        route_addition_preview_details = Subscription.calculate_prorata_details(
            unit, today, period_end,
        )
        route_addition_preview = route_addition_preview_details['amount']
    period_info = build_subscription_period_context(subscription, today)
    contract_prorata_preview = period_info.get('contract_prorata_preview')
    catalog_route_limit = get_catalog_route_limit(subscription, tariff)
    if subscription.status == Subscription.STATUS_TRIAL:
        contract_prorata_preview = compute_contract_prorata_preview(
            subscription, preview_routes, today,
        )
    amount_due = compute_amount_due(
        subscription, today, monthly_price, current_invoice, period_info,
    )

    return render(request, 'stop_check/subscription/index.html', {
        'subscription': subscription,
        'routes': routes,
        'route_count': route_count,
        'available_slots': available_slots,
        'monthly_price': monthly_price,
        'amount_due': amount_due,
        'tariff': tariff,
        'contract_form': contract_form,
        'route_request_form': route_request_form,
        'preview_routes': preview_routes,
        'pending_invoices': pending_invoices,
        'current_invoice': current_invoice,
        'pending_route_request': pending_route_request,
        'route_addition_preview': route_addition_preview,
        'can_request_additional_routes': can_add_routes,
        'base_routes_registered': base_routes_registered(org, tariff),
        'catalog_route_limit': catalog_route_limit,
        'period_info': period_info,
        'contract_prorata_preview': contract_prorata_preview,
        'route_addition_preview_details': route_addition_preview_details,
        'trial_days_left': trial_days_remaining(subscription),
    })


def _dashboard_export_context(org, year, month):
    stats = get_dashboard_stats(org, year, month)
    breakdowns = get_dashboard_breakdowns(org, year, month)
    evolution = get_dashboard_evolution(org, year, month)
    evolution_rows = [
        {
            'label': label,
            'stops': evolution['operations']['stops'][i],
            'pudo': evolution['operations']['pudo'][i],
            'pickups': evolution['operations']['pickups'][i],
            'operations_total': (
                evolution['operations']['stops'][i]
                + evolution['operations']['pudo'][i]
                + evolution['operations']['pickups'][i]
            ),
            'revenue': evolution['finance']['revenue'][i],
            'expenses': evolution['finance']['expenses'][i],
            'profit': evolution['finance']['profit'][i],
        }
        for i, label in enumerate(evolution['labels'])
    ]
    return {
        'stats': stats,
        'by_company': breakdowns['by_company'],
        'by_route': breakdowns['by_route'],
        'evolution': evolution,
        'evolution_rows': evolution_rows,
        'org': org,
        'year': year,
        'month': month,
        'month_name': MONTHS_PT[month],
    }


def _write_breakdown_csv(writer, title, rows):
    writer.writerow([])
    writer.writerow([title])
    writer.writerow([
        'Nome', 'Dias', 'Stops', 'PUDO', 'Recolhas', 'Média/dia', 'Discrepâncias', 'Dif. €',
    ])
    for row in rows:
        writer.writerow([
            row['label'],
            row['days'],
            row['stops'],
            row['pudo'],
            row['pickups'],
            row['avg_operations'],
            row['discrepancies'],
            f'{row["diff_amount"]:.2f}',
        ])


@organization_required
def export_excel(request):
    org = request.user.profile.organization
    year, month = get_period(request)
    ctx = _dashboard_export_context(org, year, month)
    stats = ctx['stats']
    evolution = ctx['evolution']

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    filename = f'stopcheck_{year}_{month:02d}.csv'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')

    writer = csv.writer(response, delimiter=';')
    writer.writerow(['StopCheck - Relatório', ctx['month_name'], year])
    writer.writerow([])
    writer.writerow(['Indicadores Gerais'])
    writer.writerow(['Dias com dados', stats['days_with_data']])
    writer.writerow(['Média Stops/dia', stats['avg_stops']])
    writer.writerow(['Média PUDO/dia', stats['avg_pudo']])
    writer.writerow(['Média Recolhas/dia', stats['avg_pickups']])
    writer.writerow(['Total Stops', stats['total_stops']])
    writer.writerow(['Total PUDO', stats['total_pudo']])
    writer.writerow(['Total Recolhas', stats['total_pickups']])
    writer.writerow(['Discrepâncias', stats['discrepancy_count']])
    writer.writerow([])
    writer.writerow(['Resumo Financeiro'])
    writer.writerow(['Receita Bruta', f'{stats["gross_revenue"]:.2f}'])
    writer.writerow(['Combustível', f'{stats["fuel_cost"]:.2f}'])
    writer.writerow(['Outras Despesas', f'{stats["other_expenses"]:.2f}'])
    writer.writerow(['Total Despesas', f'{stats["total_expenses"]:.2f}'])
    writer.writerow(['Lucro Líquido', f'{stats["net_profit"]:.2f}'])
    if stats['cost_per_operation'] is not None:
        writer.writerow(['Custo por Operação', f'{stats["cost_per_operation"]:.3f}'])
    writer.writerow([])
    writer.writerow(['Impacto das Diferenças (€)'])
    writer.writerow(['Stops', f'{stats["diff_amounts"]["stops"]:.2f}'])
    writer.writerow(['PUDO', f'{stats["diff_amounts"]["pudo"]:.2f}'])
    writer.writerow(['Recolhas', f'{stats["diff_amounts"]["pickups"]:.2f}'])
    writer.writerow(['Total', f'{stats["diff_amounts"]["total"]:.2f}'])

    _write_breakdown_csv(writer, 'Indicadores por Empresa', ctx['by_company'])
    _write_breakdown_csv(writer, 'Indicadores por Rota', ctx['by_route'])

    writer.writerow([])
    writer.writerow(['Evolução de Operações (últimos 6 meses)'])
    writer.writerow(['Mês', 'Stops', 'PUDO', 'Recolhas'])
    for i, label in enumerate(evolution['labels']):
        writer.writerow([
            label,
            evolution['operations']['stops'][i],
            evolution['operations']['pudo'][i],
            evolution['operations']['pickups'][i],
        ])

    writer.writerow([])
    writer.writerow(['Evolução Financeira (últimos 6 meses)'])
    writer.writerow(['Mês', 'Receita', 'Despesas', 'Lucro'])
    for i, label in enumerate(evolution['labels']):
        writer.writerow([
            label,
            f'{evolution["finance"]["revenue"][i]:.2f}',
            f'{evolution["finance"]["expenses"][i]:.2f}',
            f'{evolution["finance"]["profit"][i]:.2f}',
        ])

    return response


@organization_required
def export_pdf(request):
    org = request.user.profile.organization
    year, month = get_period(request)
    return render(request, 'stop_check/exports/pdf_report.html', _dashboard_export_context(org, year, month))
