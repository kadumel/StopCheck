from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from .models import (
    DailyComparison,
    DeliveryCompany,
    Driver,
    Expense,
    ExpenseCategory,
    FuelRecord,
    Organization,
    RateConfig,
    UserProfile,
    Vehicle,
)


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = 'w-full px-4 py-2.5 rounded-lg border border-slate-300 bg-white text-slate-800 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none transition'
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'w-4 h-4 text-emerald-600 rounded focus:ring-emerald-500'
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs['class'] = css + ' min-h-[100px]'
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = css
            else:
                field.widget.attrs['class'] = css


class LoginForm(StyledFormMixin, AuthenticationForm):
    username = forms.CharField(label='Email ou Utilizador')
    password = forms.CharField(label='Palavra-passe', widget=forms.PasswordInput)


class RegisterForm(StyledFormMixin, UserCreationForm):
    organization_name = forms.CharField(label='Nome da Empresa', max_length=200)
    email = forms.EmailField(label='Email')
    first_name = forms.CharField(label='Nome', max_length=150)
    last_name = forms.CharField(label='Apelido', max_length=150, required=False)
    phone = forms.CharField(label='Telefone', max_length=20, required=False)

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2')

    def clean_email(self):
        email = self.cleaned_data['email'].lower().strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Este email já está registado.')
        return email


class EmailVerificationForm(StyledFormMixin, forms.Form):
    code = forms.CharField(
        label='Código de verificação',
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            'inputmode': 'numeric',
            'pattern': '[0-9]{6}',
            'autocomplete': 'one-time-code',
            'placeholder': '000000',
            'class': 'w-full px-4 py-3 rounded-lg border border-slate-300 text-center text-2xl tracking-[0.5em] font-mono focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none',
        }),
    )

    def clean_code(self):
        code = self.cleaned_data['code'].strip()
        if not code.isdigit() or len(code) != 6:
            raise forms.ValidationError('Introduza o código de 6 dígitos.')
        return code


class VehicleForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ['plate', 'brand', 'model', 'year', 'fuel_type', 'is_active']
        labels = {
            'plate': 'Matrícula',
            'brand': 'Marca',
            'model': 'Modelo',
            'year': 'Ano',
            'fuel_type': 'Combustível',
            'is_active': 'Ativo',
        }


class DriverForm(StyledFormMixin, forms.ModelForm):
    create_account = forms.BooleanField(
        required=False, initial=True, label='Criar conta de acesso (login)'
    )
    username = forms.CharField(
        required=False, label='Utilizador', max_length=150,
        help_text='Obrigatório se criar conta de acesso.',
    )
    password = forms.CharField(
        required=False, label='Palavra-passe', widget=forms.PasswordInput,
    )

    class Meta:
        model = Driver
        fields = ['name', 'email', 'phone', 'license_number', 'default_vehicle', 'is_active']
        labels = {
            'name': 'Nome',
            'email': 'Email',
            'phone': 'Telefone',
            'license_number': 'Carta de Condução',
            'default_vehicle': 'Veículo Padrão',
            'is_active': 'Ativo',
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('create_account'):
            if not cleaned.get('username'):
                self.add_error('username', 'Indique um utilizador para a conta.')
            if not cleaned.get('password') and not self.instance.pk:
                self.add_error('password', 'Indique uma palavra-passe.')
            if cleaned.get('username') and User.objects.filter(
                username=cleaned['username']
            ).exclude(pk=self.instance.user_id if self.instance.user_id else None).exists():
                self.add_error('username', 'Este utilizador já existe.')
        return cleaned

    def save(self, commit=True):
        driver = super().save(commit=False)
        if hasattr(self, 'organization'):
            driver.organization = self.organization
        if commit:
            driver.save()
            self._create_user_account(driver)
        return driver

    def _create_user_account(self, driver):
        if not self.cleaned_data.get('create_account') or not self.cleaned_data.get('username'):
            return
        if driver.user:
            user = driver.user
            user.username = self.cleaned_data['username']
            if self.cleaned_data.get('password'):
                user.set_password(self.cleaned_data['password'])
            user.email = driver.email or user.email
            user.save()
            return
        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            password=self.cleaned_data['password'],
            email=driver.email,
            first_name=driver.name.split()[0] if driver.name else '',
        )
        UserProfile.objects.create(
            user=user,
            organization=driver.organization,
            role=UserProfile.ROLE_DRIVER,
            phone=driver.phone,
        )
        driver.user = user
        driver.save(update_fields=['user'])


class DailyComparisonForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = DailyComparison
        fields = [
            'driver', 'vehicle', 'date',
            'driver_stops', 'driver_pudo', 'driver_pickups',
            'company_stops', 'company_pudo', 'company_pickups',
            'notes',
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            'driver': 'Motorista',
            'vehicle': 'Veículo',
            'date': 'Data',
            'driver_stops': 'Paradas (Seus Dados)',
            'driver_pudo': 'PUDO (Seus Dados)',
            'driver_pickups': 'Recolhas (Seus Dados)',
            'company_stops': 'Paradas (Empresa)',
            'company_pudo': 'PUDO (Empresa)',
            'company_pickups': 'Recolhas (Empresa)',
            'notes': 'Observações',
        }


class FuelRecordForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FuelRecord
        fields = ['vehicle', 'driver', 'date', 'liters', 'price_per_liter', 'odometer', 'station', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }
        labels = {
            'vehicle': 'Veículo',
            'driver': 'Motorista',
            'date': 'Data',
            'liters': 'Litros',
            'price_per_liter': 'Preço por Litro (€)',
            'odometer': 'Quilometragem',
            'station': 'Posto',
            'notes': 'Observações',
        }


class ExpenseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['category', 'vehicle', 'date', 'description', 'amount', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


class RateConfigForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = RateConfig
        fields = ['price_per_stop', 'price_per_pudo', 'price_per_pickup']


class DeliveryCompanyForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = DeliveryCompany
        fields = ['name', 'contact_email', 'contact_phone', 'notes', 'is_active']


class CompanyImportForm(StyledFormMixin, forms.Form):
    delivery_company = forms.ModelChoiceField(
        queryset=DeliveryCompany.objects.none(),
        required=False,
        label='Empresa de Entrega',
    )
    file = forms.FileField(
        label='Ficheiro CSV ou Excel',
        help_text='Colunas: data, motorista, paradas, pudo, recolhas',
    )
