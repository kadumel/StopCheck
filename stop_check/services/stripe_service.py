import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def stripe_enabled():
    return bool(getattr(settings, 'STRIPE_SECRET_KEY', ''))


def get_stripe():
    if not stripe_enabled():
        return None
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def create_checkout_session(organization, success_url, cancel_url):
    stripe = get_stripe()
    if not stripe:
        raise ValueError('Stripe não configurado. Defina STRIPE_SECRET_KEY.')

    subscription = organization.subscription
    route_count = max(organization.route_count, 1)
    monthly_price = subscription.calculate_price(subscription.contracted_routes or route_count)
    amount_cents = int(monthly_price * 100)

    customer_id = subscription.stripe_customer_id
    if not customer_id:
        customer = stripe.Customer.create(
            email=organization.email,
            name=organization.name,
            metadata={'organization_id': organization.pk},
        )
        customer_id = customer.id
        subscription.stripe_customer_id = customer_id
        subscription.save(update_fields=['stripe_customer_id'])

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode='subscription',
        line_items=[{
            'price_data': {
                'currency': 'eur',
                'product_data': {
                    'name': f'StopCheck — {route_count} rota(s)',
                    'description': 'Controlo de entregas, frota e produtividade',
                },
                'unit_amount': amount_cents,
                'recurring': {'interval': 'month'},
            },
            'quantity': 1,
        }],
        metadata={'organization_id': organization.pk},
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return session


def create_customer_portal_session(organization, return_url):
    stripe = get_stripe()
    if not stripe or not organization.subscription.stripe_customer_id:
        raise ValueError('Sem cliente Stripe associado.')

    session = stripe.billing_portal.Session.create(
        customer=organization.subscription.stripe_customer_id,
        return_url=return_url,
    )
    return session


def handle_webhook_event(payload, sig_header):
    stripe = get_stripe()
    if not stripe:
        return None

    from stop_check.models import Subscription

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except Exception as exc:
        logger.warning('Stripe webhook inválido: %s', exc)
        raise

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        org_id = session.get('metadata', {}).get('organization_id')
        if org_id:
            try:
                sub = Subscription.objects.select_related('organization').get(
                    organization_id=org_id
                )
                sub.status = Subscription.STATUS_ACTIVE
                sub.stripe_subscription_id = session.get('subscription', '')
                sub.last_payment_date = timezone.localdate()
                sub.save(update_fields=[
                    'status', 'stripe_subscription_id', 'last_payment_date',
                ])
            except Subscription.DoesNotExist:
                pass

    elif event['type'] == 'customer.subscription.updated':
        sub_data = event['data']['object']
        stripe_sub_id = sub_data['id']
        try:
            sub = Subscription.objects.get(stripe_subscription_id=stripe_sub_id)
            if sub_data['status'] == 'active':
                sub.status = Subscription.STATUS_ACTIVE
            elif sub_data['status'] in ('past_due', 'unpaid'):
                sub.status = Subscription.STATUS_SUSPENDED
            elif sub_data['status'] == 'canceled':
                sub.status = Subscription.STATUS_CANCELLED
            if sub_data.get('current_period_end'):
                sub.current_period_end = datetime.fromtimestamp(
                    sub_data['current_period_end'], tz=timezone.utc
                )
            sub.save()
        except Subscription.DoesNotExist:
            pass

    elif event['type'] == 'customer.subscription.deleted':
        sub_data = event['data']['object']
        Subscription.objects.filter(
            stripe_subscription_id=sub_data['id']
        ).update(status=Subscription.STATUS_CANCELLED)

    elif event['type'] == 'invoice.paid':
        invoice = event['data']['object']
        customer_id = invoice.get('customer')
        if customer_id:
            Subscription.objects.filter(stripe_customer_id=customer_id).update(
                last_payment_date=timezone.localdate(),
                status=Subscription.STATUS_ACTIVE,
            )

    return event
