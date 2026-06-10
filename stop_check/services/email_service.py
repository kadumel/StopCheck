import logging
import secrets
from datetime import timedelta

import requests
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from stop_check.models import EmailVerification
from stop_check.services.email_templates import build_verification_email

logger = logging.getLogger(__name__)

VERIFICATION_EXPIRY_MINUTES = 15
MAX_ATTEMPTS = 5


def generate_verification_code():
    return f'{secrets.randbelow(1000000):06d}'


def create_verification(email, payload):
    EmailVerification.objects.filter(email=email, is_verified=False).delete()
    code = generate_verification_code()
    verification = EmailVerification.objects.create(
        email=email,
        code_hash=make_password(code),
        payload=payload,
        expires_at=timezone.now() + timedelta(minutes=VERIFICATION_EXPIRY_MINUTES),
    )
    return verification, code


def verify_code(email, code):
    verification = (
        EmailVerification.objects.filter(email=email, is_verified=False)
        .order_by('-created_at')
        .first()
    )
    if not verification:
        return None, 'Não existe verificação pendente para este email.'
    if verification.is_expired:
        return None, 'O código expirou. Solicite um novo código.'
    if verification.attempts >= MAX_ATTEMPTS:
        return None, 'Número máximo de tentativas atingido. Solicite um novo código.'

    verification.attempts += 1
    verification.save(update_fields=['attempts'])

    if not check_password(code, verification.code_hash):
        remaining = MAX_ATTEMPTS - verification.attempts
        if remaining <= 0:
            return None, 'Código incorreto. Solicite um novo código.'
        return None, f'Código incorreto. Restam {remaining} tentativa(s).'

    verification.is_verified = True
    verification.save(update_fields=['is_verified'])
    return verification, None


def send_verification_email(email, code, organization_name, first_name):
    webhook_url = getattr(settings, 'N8N_EMAIL_WEBHOOK_URL', '')
    email_secret = getattr(settings, 'EMAIL_SECRET', '')

    if not webhook_url:
        if settings.DEBUG:
            logger.warning('N8N_EMAIL_WEBHOOK_URL não configurado. Código: %s', code)
            return True, code
        raise ValueError('Serviço de email não configurado.')

    headers = {
        'Content-Type': 'application/json',
        'X-Webhook-Secret': email_secret,
    }
    body = build_verification_email(email, code, organization_name, first_name)

    response = requests.post(webhook_url, json=body, headers=headers, timeout=15)
    response.raise_for_status()
    return True, None


def resend_verification(email):
    verification = (
        EmailVerification.objects.filter(email=email, is_verified=False)
        .order_by('-created_at')
        .first()
    )
    if not verification:
        return None, None, 'Sessão de verificação expirada. Registe-se novamente.'

    code = generate_verification_code()
    verification.code_hash = make_password(code)
    verification.attempts = 0
    verification.expires_at = timezone.now() + timedelta(minutes=VERIFICATION_EXPIRY_MINUTES)
    verification.save()

    return verification, code, None
