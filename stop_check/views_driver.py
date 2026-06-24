from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.middleware.csrf import get_token
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .decorators import driver_required, get_home_url_name
from .models import DailyComparison, StopEvent
from .stop_logging import (
    DriverDataLockedError,
    PendingPastDaysError,
    decrement_driver_count,
    get_or_create_comparison_for_route,
    get_or_create_today_comparison,
    get_pending_past_comparisons,
    get_required_work_date,
    get_routes_for_date,
    get_today_routes,
    get_work_date,
    get_work_routes,
    log_stop_event,
    set_driver_counts,
    submit_driver_data,
    assert_can_work_on_route,
)


def _get_driver(request):
    if hasattr(request.user, 'driver_profile'):
        return request.user.driver_profile
    return None


@never_cache
def service_worker(request):
    sw_path = settings.BASE_DIR / 'static' / 'sw.js'
    response = HttpResponse(sw_path.read_text(), content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    return response


@driver_required
@ensure_csrf_cookie
@never_cache
def driver_app(request):
    driver = _get_driver(request)
    if not driver:
        messages.error(request, 'Perfil de motorista não associado à sua conta.')
        return redirect('dashboard')

    org = request.user.profile.organization
    today = timezone.localdate()
    work_date = get_work_date(org, driver)
    is_catch_up = work_date < today
    pending_past = list(get_pending_past_comparisons(org, driver))
    work_routes = list(get_work_routes(org, driver)[0])
    route_id = request.GET.get('rota')
    selected_route = None

    if route_id:
        selected_route = next((r for r in work_routes if str(r.pk) == route_id), None)
    elif len(work_routes) == 1:
        selected_route = work_routes[0]

    comparison = None
    if selected_route:
        comparison = get_or_create_comparison_for_route(selected_route)
    elif not work_routes and not is_catch_up:
        messages.warning(
            request,
            'Não tem nenhuma rota atribuída para hoje. Contacte o gestor.',
        )

    recent = StopEvent.objects.filter(
        organization=org, driver=driver, recorded_at__date=work_date
    ).select_related('vehicle', 'route')[:10]

    return render(request, 'stop_check/mobile/app.html', {
        'driver': driver,
        'comparison': comparison,
        'today_routes': work_routes,
        'selected_route': selected_route,
        'recent_events': recent,
        'today': today,
        'work_date': work_date,
        'is_catch_up': is_catch_up,
        'pending_past_count': len(pending_past),
    })


def _comparison_json(comp):
    return {
        'ok': True,
        'stops': comp.driver_stops,
        'pudo': comp.driver_pudo,
        'pickups': comp.driver_pickups,
        'total': comp.driver_total,
        'locked': comp.driver_data_locked,
        'locked_by_admin': comp.driver_locked_by_admin,
    }


def _parse_nonneg_int(value, default=0):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _get_route_for_driver_request(org, driver, route_id):
    if not route_id:
        return None
    routes = get_work_routes(org, driver)[0]
    return routes.filter(pk=route_id).first()


@driver_required
@ensure_csrf_cookie
@never_cache
@require_GET
def driver_csrf(request):
    return JsonResponse({'csrfToken': get_token(request)})


@csrf_exempt
@driver_required
@require_POST
def driver_log_event(request):
    driver = _get_driver(request)
    if not driver:
        return JsonResponse({'ok': False, 'error': 'Motorista não encontrado'}, status=400)

    org = request.user.profile.organization
    route_id = request.POST.get('route_id')
    route = _get_route_for_driver_request(org, driver, route_id)
    action = request.POST.get('action', 'increment')

    if action == 'set':
        if not route:
            return JsonResponse({'ok': False, 'error': 'Rota inválida'}, status=400)
        comp = get_or_create_comparison_for_route(route)
        try:
            assert_can_work_on_route(org, driver, route)
            comp = set_driver_counts(
                comp,
                _parse_nonneg_int(request.POST.get('stops')),
                _parse_nonneg_int(request.POST.get('pudo')),
                _parse_nonneg_int(request.POST.get('pickups')),
            )
        except DriverDataLockedError as exc:
            return JsonResponse({'ok': False, 'error': str(exc), 'locked': True}, status=403)
        except PendingPastDaysError as exc:
            return JsonResponse({'ok': False, 'error': str(exc)}, status=403)
        except ValueError as exc:
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
        return JsonResponse(_comparison_json(comp))

    event_type = request.POST.get('event_type')
    valid = {StopEvent.TYPE_STOP, StopEvent.TYPE_PUDO, StopEvent.TYPE_PICKUP}
    if event_type not in valid:
        return JsonResponse({'ok': False, 'error': 'Tipo inválido'}, status=400)

    if route_id and not route:
        return JsonResponse({'ok': False, 'error': 'Rota inválida'}, status=400)

    try:
        if action == 'decrement':
            if not route:
                return JsonResponse({'ok': False, 'error': 'Rota inválida'}, status=400)
            comp = get_or_create_comparison_for_route(route)
            assert_can_work_on_route(org, driver, route)
            comp = decrement_driver_count(comp, event_type)
        else:
            comp = log_stop_event(org, driver, event_type, route=route)
    except DriverDataLockedError as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'locked': True}, status=403)
    except PendingPastDaysError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=403)
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    return JsonResponse(_comparison_json(comp))


@csrf_exempt
@driver_required
@require_POST
def driver_submit_data(request):
    driver = _get_driver(request)
    if not driver:
        return JsonResponse({'ok': False, 'error': 'Motorista não encontrado'}, status=400)

    org = request.user.profile.organization
    route_id = request.POST.get('route_id')
    comparison_id = request.POST.get('comparison_id')
    route = None

    if comparison_id:
        comp = DailyComparison.objects.filter(
            pk=comparison_id,
            organization=org,
            driver=driver,
        ).select_related('route').first()
        if not comp or not comp.route:
            return JsonResponse({'ok': False, 'error': 'Registo inválido'}, status=400)
        route = comp.route
    else:
        route = _get_route_for_driver_request(org, driver, route_id)
        if not route:
            return JsonResponse({'ok': False, 'error': 'Rota inválida'}, status=400)
        comp = get_or_create_comparison_for_route(route)

    if comp.driver_data_locked:
        if comp.driver_locked_by_admin:
            error = 'O gestor preencheu os dados deste dia. Contacte-o para alterar.'
        else:
            error = 'Registo já concluído. Contacte o gestor para alterar.'
        return JsonResponse({
            'ok': False,
            'error': error,
            'locked': True,
            'locked_by_admin': comp.driver_locked_by_admin,
        }, status=400)

    try:
        assert_can_work_on_route(org, driver, route)
    except PendingPastDaysError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=403)

    comp = submit_driver_data(comp)
    return JsonResponse(_comparison_json(comp))


@driver_required
@ensure_csrf_cookie
@never_cache
def driver_history(request):
    driver = _get_driver(request)
    org = request.user.profile.organization
    today = timezone.localdate()
    comparisons = DailyComparison.objects.filter(
        organization=org, driver=driver
    ).select_related('route', 'vehicle').order_by('-date')[:30]
    return render(request, 'stop_check/mobile/history.html', {
        'driver': driver,
        'comparisons': comparisons,
        'today': today,
    })
