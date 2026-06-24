from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from .models import Subscription, UserProfile

SUBSCRIPTION_EXEMPT_URLS = frozenset({
    'subscription',
    'logout',
    'offline',
})


def get_home_url_name(user):
    if hasattr(user, 'profile') and user.profile.is_driver:
        return 'driver_app'
    return 'dashboard'


def _subscription_blocked_reason(subscription):
    if subscription is None:
        return None
    if subscription.status == Subscription.STATUS_SUSPENDED:
        return 'A sua assinatura está suspensa por falta de pagamento. Regularize em Assinatura.'
    if subscription.trial_expired:
        return 'O período experimental terminou. Contrate um plano para continuar a usar o StopCheck.'
    if subscription.status == Subscription.STATUS_CANCELLED:
        return 'A assinatura foi cancelada. Contrate novamente para recuperar o acesso.'
    return None


def organization_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not hasattr(request.user, 'profile'):
            messages.info(
                request,
                'Complete o registo da sua empresa para aceder ao StopCheck.',
            )
            return redirect('register')
        url_name = getattr(request.resolver_match, 'url_name', None)
        if url_name not in SUBSCRIPTION_EXEMPT_URLS:
            org = request.user.profile.organization
            subscription = getattr(org, 'subscription', None)
            reason = _subscription_blocked_reason(subscription)
            if reason:
                messages.error(request, reason)
                return redirect('subscription')
        return view_func(request, *args, **kwargs)
    return wrapper


def manager_required(view_func):
    @wraps(view_func)
    @organization_required
    def wrapper(request, *args, **kwargs):
        if not request.user.profile.is_manager:
            return redirect(get_home_url_name(request.user))
        return view_func(request, *args, **kwargs)
    return wrapper


def admin_required(view_func):
    @wraps(view_func)
    @organization_required
    def wrapper(request, *args, **kwargs):
        if not request.user.profile.is_admin:
            return redirect(get_home_url_name(request.user))
        return view_func(request, *args, **kwargs)
    return wrapper


def driver_required(view_func):
    @wraps(view_func)
    @organization_required
    def wrapper(request, *args, **kwargs):
        if not request.user.profile.is_driver:
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


def manager_or_driver_own_data(view_func):
    """Gestores acedem a tudo; motoristas só aos seus dados."""
    @wraps(view_func)
    @organization_required
    def wrapper(request, *args, **kwargs):
        profile = request.user.profile
        if profile.is_manager:
            return view_func(request, *args, **kwargs)
        if profile.is_driver and hasattr(request.user, 'driver_profile'):
            return view_func(request, *args, **kwargs)
        return redirect(get_home_url_name(request.user))
    return wrapper
