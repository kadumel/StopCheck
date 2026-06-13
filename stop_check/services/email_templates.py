from django.conf import settings
from django.template.loader import render_to_string

VERIFICATION_EXPIRY_MINUTES = 15


def build_verification_email(email, code, organization_name, first_name):
    site_url = getattr(settings, 'SITE_URL', '').rstrip('/')
    verify_url = f'{site_url}/registar/verificar/' if site_url else ''

    assunto = f'Confirme o seu email — {organization_name} | StopCheck'

    display_name = first_name.strip() or 'Utilizador'

    texto = (
        f'Olá {display_name},\n\n'
        f'Obrigado por registar a empresa {organization_name} no StopCheck.\n\n'
        f'O seu código de verificação é: {code}\n\n'
        f'Este código é válido por {VERIFICATION_EXPIRY_MINUTES} minutos.\n\n'
    )
    if verify_url:
        texto += f'Confirme em: {verify_url}\n\n'
    texto += (
        'Se não solicitou este registo, ignore este email.\n\n'
        'StopCheck — Controlo de entregas e produtividade\n'
    )
    if site_url:
        texto += f'{site_url}\n'

    html = render_to_string('stop_check/emails/verification_email.html', {
        'assunto': assunto,
        'first_name': display_name,
        'organization_name': organization_name,
        'code': code,
        'expiry_minutes': VERIFICATION_EXPIRY_MINUTES,
        'site_url': site_url,
        'verify_url': verify_url,
    })

    return {
        'para': [email],
        'assunto': assunto,
        'texto': texto,
        'html': html,
        'cc': [],
        'bcc': [],
        'reply_to': [],
        # Campos auxiliares para o N8N
        'email': email,
        'code': code,
        'organization_name': organization_name,
        'first_name': display_name,
    }


def build_payment_report_email(subscription, notify_email):
    org = subscription.organization
    amount = subscription.monthly_price
    method_label = subscription.get_payment_method_display()

    assunto = f'Pagamento informado — {org.name} | StopCheck'

    texto = (
        f'A empresa {org.name} informou que efectuou o pagamento da assinatura.\n\n'
        f'Email: {org.email}\n'
        f'Telefone: {org.phone or "—"}\n'
        f'NIF: {org.nif or "—"}\n'
        f'Rotas contratadas: {subscription.contracted_routes}\n'
        f'Valor mensal: {amount:.2f} €\n'
        f'Forma de pagamento: {method_label}\n\n'
        f'Confirme o recebimento no banco e active a assinatura no admin do StopCheck.\n'
    )

    html = render_to_string('stop_check/emails/payment_report_email.html', {
        'assunto': assunto,
        'organization': org,
        'subscription': subscription,
        'amount': amount,
        'method_label': method_label,
    })

    return {
        'para': [notify_email],
        'assunto': assunto,
        'texto': texto,
        'html': html,
        'cc': [],
        'bcc': [],
        'reply_to': [org.email] if org.email else [],
        'organization_name': org.name,
        'organization_email': org.email,
        'contracted_routes': subscription.contracted_routes,
        'amount': str(amount),
        'payment_method': subscription.payment_method,
    }
