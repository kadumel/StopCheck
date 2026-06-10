from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from .models import UserProfile


def get_home_url_name(user):
    if hasattr(user, 'profile') and user.profile.is_driver:
        return 'driver_app'
    return 'dashboard'


def organization_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not hasattr(request.user, 'profile'):
            return redirect('register')
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
