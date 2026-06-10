from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .decorators import driver_required, get_home_url_name
from .models import DailyComparison, StopEvent, UserProfile
from .stop_logging import get_or_create_today_comparison, log_stop_event


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
    comp = get_or_create_today_comparison(org, driver)
    recent = StopEvent.objects.filter(
        organization=org, driver=driver
    ).select_related('vehicle')[:10]

    return render(request, 'stop_check/mobile/app.html', {
        'driver': driver,
        'comparison': comp,
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
    comp = log_stop_event(org, driver, event_type)

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
    ).order_by('-date')[:30]
    return render(request, 'stop_check/mobile/history.html', {
        'driver': driver,
        'comparisons': comparisons,
    })
