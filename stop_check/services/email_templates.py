from django.conf import settings
from django.template.loader import render_to_string

from stop_check.models import SubscriptionTariff

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


def build_payment_report_email(subscription, notify_email, invoice=None):
    org = subscription.organization
    amount = invoice.amount if invoice else subscription.monthly_price
    method_label = subscription.get_payment_method_display()
    period_label = ''
    if invoice:
        period_label = (
            f'{invoice.period_start.strftime("%d/%m/%Y")} — '
            f'{invoice.period_end.strftime("%d/%m/%Y")}'
        )

    assunto = f'Pagamento informado — {org.name} | StopCheck'

    texto = (
        f'A empresa {org.name} informou que efectuou o pagamento da assinatura.\n\n'
        f'Email: {org.email}\n'
        f'Telefone: {org.phone or "—"}\n'
        f'NIF: {org.nif or "—"}\n'
        f'Rotas contratadas: {subscription.contracted_routes}\n'
        f'Valor: {amount:.2f} €\n'
    )
    if period_label:
        texto += f'Período: {period_label}\n'
    texto += (
        f'Forma de pagamento: {method_label}\n\n'
        f'Confirme o recebimento no banco e active a assinatura no admin do StopCheck.\n'
    )

    html = render_to_string('stop_check/emails/payment_report_email.html', {
        'assunto': assunto,
        'organization': org,
        'subscription': subscription,
        'invoice': invoice,
        'amount': amount,
        'method_label': method_label,
        'period_label': period_label,
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


def build_subscription_invoice_email(invoice):
    org = invoice.organization
    subscription = invoice.subscription
    tariff = SubscriptionTariff.get()

    assunto = f'Cobrança StopCheck — {org.name} — {invoice.amount:.2f} €'

    period_label = (
        f'{invoice.period_start.strftime("%d/%m/%Y")} a '
        f'{invoice.period_end.strftime("%d/%m/%Y")}'
    )
    texto = (
        f'Olá,\n\n'
        f'A cobrança da assinatura StopCheck de {org.name} está disponível.\n\n'
        f'Tipo: {invoice.get_invoice_type_display()}\n'
        f'Período: {period_label}\n'
        f'Rotas: {invoice.route_count}\n'
        f'Valor: {invoice.amount:.2f} €\n'
        f'Pagamento até: {invoice.due_date.strftime("%d/%m/%Y")}\n'
        f'Forma de pagamento: {subscription.get_payment_method_display() or "—"}\n\n'
    )
    if tariff.mbway_phone:
        texto += f'MB Way: {tariff.mbway_phone}\n'
    if tariff.iban:
        texto += f'IBAN: {tariff.iban}\n'
        if tariff.iban_holder:
            texto += f'Titular: {tariff.iban_holder}\n'
    texto += (
        '\nO pagamento é antecipado. Após o dia limite, o acesso poderá ser bloqueado.\n\n'
        'StopCheck\n'
    )

    html = render_to_string('stop_check/emails/subscription_invoice_email.html', {
        'assunto': assunto,
        'organization': org,
        'subscription': subscription,
        'invoice': invoice,
        'tariff': tariff,
        'period_label': period_label,
    })

    return {
        'para': [org.email],
        'assunto': assunto,
        'texto': texto,
        'html': html,
        'cc': [],
        'bcc': [],
        'reply_to': [],
        'organization_name': org.name,
        'invoice_id': invoice.pk,
        'amount': str(invoice.amount),
    }


def build_route_addition_request_email(route_request):
    org = route_request.organization
    subscription = route_request.subscription
    invoice = route_request.invoice
    tariff = SubscriptionTariff.get()
    new_total = (subscription.contracted_routes or 0) + route_request.additional_routes

    assunto = (
        f'Pedido de rotas adicionais — {org.name} — '
        f'{invoice.amount:.2f} € | StopCheck'
    )
    period_label = (
        f'{invoice.period_start.strftime("%d/%m/%Y")} a '
        f'{invoice.period_end.strftime("%d/%m/%Y")}'
    )
    texto = (
        f'Olá,\n\n'
        f'Recebemos o seu pedido de contratação de rotas adicionais no StopCheck.\n\n'
        f'Empresa: {org.name}\n'
        f'Rotas adicionais solicitadas: {route_request.additional_routes}\n'
        f'Total de rotas após pagamento: {new_total}\n'
        f'Valor proporcional: {invoice.amount:.2f} €\n'
        f'Período: {period_label}\n'
        f'Pagar até: {invoice.due_date.strftime("%d/%m/%Y")}\n\n'
        f'Após confirmação do pagamento, poderá registar as novas rotas em '
        f'Empresa / Rota no painel do StopCheck.\n\n'
    )
    if tariff.mbway_phone:
        texto += f'MB Way: {tariff.mbway_phone}\n'
    if tariff.iban:
        texto += f'IBAN: {tariff.iban}\n'
        if tariff.iban_holder:
            texto += f'Titular: {tariff.iban_holder}\n'
    texto += (
        '\nQuando efectuar o pagamento, informe-nos na página Assinatura.\n\n'
        'StopCheck\n'
    )

    html = render_to_string('stop_check/emails/route_addition_request_email.html', {
        'assunto': assunto,
        'organization': org,
        'subscription': subscription,
        'route_request': route_request,
        'invoice': invoice,
        'tariff': tariff,
        'new_total': new_total,
        'period_label': period_label,
    })

    return {
        'para': [org.email],
        'assunto': assunto,
        'texto': texto,
        'html': html,
        'cc': [],
        'bcc': [],
        'reply_to': [],
        'organization_name': org.name,
        'additional_routes': route_request.additional_routes,
        'amount': str(invoice.amount),
    }
