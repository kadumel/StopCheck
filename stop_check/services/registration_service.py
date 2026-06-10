from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.utils import timezone

from stop_check.models import (
    ExpenseCategory,
    Organization,
    RateConfig,
    Subscription,
    UserProfile,
)


def build_registration_payload(cleaned_data):
    return {
        'organization_name': cleaned_data['organization_name'],
        'username': cleaned_data['username'],
        'email': cleaned_data['email'],
        'first_name': cleaned_data['first_name'],
        'last_name': cleaned_data.get('last_name', ''),
        'phone': cleaned_data.get('phone', ''),
        'password_hash': make_password(cleaned_data['password1']),
    }


def create_account_from_payload(payload):
    if User.objects.filter(username=payload['username']).exists():
        raise ValueError('Este utilizador já existe.')
    if User.objects.filter(email=payload['email']).exists():
        raise ValueError('Este email já está registado.')
    if Organization.objects.filter(email=payload['email']).exists():
        raise ValueError('Já existe uma empresa com este email.')

    user = User(
        username=payload['username'],
        email=payload['email'],
        first_name=payload['first_name'],
        last_name=payload.get('last_name', ''),
    )
    user.password = payload['password_hash']
    user.save()

    org = Organization.objects.create(
        name=payload['organization_name'],
        email=payload['email'],
        phone=payload.get('phone', ''),
    )
    trial_end = timezone.now().date() + timedelta(days=14)
    Subscription.objects.create(organization=org, trial_end_date=trial_end)
    RateConfig.objects.create(organization=org)
    UserProfile.objects.create(
        user=user,
        organization=org,
        role=UserProfile.ROLE_ADMIN,
        phone=payload.get('phone', ''),
    )
    default_categories = [
        ('Manutenção', '#ef4444'),
        ('Seguro', '#3b82f6'),
        ('Portagens', '#f59e0b'),
        ('Estacionamento', '#8b5cf6'),
        ('Outros', '#64748b'),
    ]
    for name, color in default_categories:
        ExpenseCategory.objects.create(organization=org, name=name, color=color)

    return user
