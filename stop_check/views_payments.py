import json

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .decorators import manager_required
from .services import stripe_service


@manager_required
def stripe_checkout(request):
    org = request.user.profile.organization
    try:
        session = stripe_service.create_checkout_session(
            org,
            success_url=request.build_absolute_uri(reverse('subscription') + '?paid=1'),
            cancel_url=request.build_absolute_uri(reverse('subscription')),
        )
        return redirect(session.url)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('subscription')


@manager_required
def stripe_portal(request):
    org = request.user.profile.organization
    try:
        session = stripe_service.create_customer_portal_session(
            org,
            return_url=request.build_absolute_uri(reverse('subscription')),
        )
        return redirect(session.url)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('subscription')


@csrf_exempt
@require_POST
def stripe_webhook(request):
    if not stripe_service.stripe_enabled():
        return HttpResponse(status=400)

    sig = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    try:
        stripe_service.handle_webhook_event(request.body, sig)
    except Exception:
        return HttpResponse(status=400)
    return HttpResponse(status=200)
