from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .decorators import driver_required, get_home_url_name
from .models import DailyComparison, StopEvent
from .stop_logging import (
    get_or_create_comparison_for_route,
    get_or_create_today_comparison,
    get_today_routes,
    log_stop_event,
)


def _get_driver(request):
    if hasattr(request.user, 'driver_profile'):
        return request.user.driver_profile
    return None


@driver_required
def driver_app(request):
    driver = _get_driver(request)
    if not driver:
        messages.error(request, 'Perfil de motorista não associado à sua conta.')
        return redirect('dashboard')

    org = request.user.profile.organization
    today_routes = list(get_today_routes(org, driver))
    route_id = request.GET.get('rota')
    selected_route = None

    if route_id:
        selected_route = next((r for r in today_routes if str(r.pk) == route_id), None)
    elif len(today_routes) == 1:
        selected_route = today_routes[0]

    comparison = None
    if selected_route:
        comparison = get_or_create_comparison_for_route(selected_route)
    elif not today_routes:
        messages.warning(
            request,
            'Não tem nenhuma rota atribuída para hoje. Contacte o gestor.',
        )

    recent = StopEvent.objects.filter(
        organization=org, driver=driver, recorded_at__date=timezone.localdate()
    ).select_related('vehicle', 'route')[:10]

    return render(request, 'stop_check/mobile/app.html', {
        'driver': driver,
        'comparison': comparison,
        'today_routes': today_routes,
        'selected_route': selected_route,
        'recent_events': recent,
        'today': timezone.localdate(),
    })


@driver_required
@require_POST
def driver_log_event(request):
    driver = _get_driver(request)
    if not driver:
        return JsonResponse({'ok': False, 'error': 'Motorista não encontrado'}, status=400)

    event_type = request.POST.get('event_type')
    valid = {StopEvent.TYPE_STOP, StopEvent.TYPE_PUDO, StopEvent.TYPE_PICKUP}
    if event_type not in valid:
        return JsonResponse({'ok': False, 'error': 'Tipo inválido'}, status=400)

    org = request.user.profile.organization
    route_id = request.POST.get('route_id')
    route = None
    if route_id:
        route = get_today_routes(org, driver).filter(pk=route_id).first()
        if not route:
            return JsonResponse({'ok': False, 'error': 'Rota inválida'}, status=400)

    try:
        comp = log_stop_event(org, driver, event_type, route=route)
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    return JsonResponse({
        'ok': True,
        'stops': comp.driver_stops,
        'pudo': comp.driver_pudo,
        'pickups': comp.driver_pickups,
        'total': comp.driver_total,
    })


@driver_required
def driver_history(request):
    driver = _get_driver(request)
    org = request.user.profile.organization
    comparisons = DailyComparison.objects.filter(
        organization=org, driver=driver
    ).select_related('route', 'vehicle').order_by('-date')[:30]
    return render(request, 'stop_check/mobile/history.html', {
        'driver': driver,
        'comparisons': comparisons,
    })
