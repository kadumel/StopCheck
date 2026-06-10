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
