import re
from decimal import Decimal

from datetime import date

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from .services.production_service import DEFAULT_WEEKDAYS, WEEKDAY_LABELS, get_dates_for_month

from .models import (
    CompanyRoute,
    ContractingCompany,
    DailyComparison,
    DeliveryCompany,
    Driver,
    Expense,
    FinancialAccount,
    FuelRecord,
    Organization,
    RateConfig,
    Revenue,
    Route,
    Subscription,
    UserProfile,
    Vehicle,
)


CHOICE_INPUT_CLASS = (
    'w-4 h-4 shrink-0 text-emerald-600 border-slate-300 focus:ring-emerald-500'
)


MONTH_CHOICES = [
    (1, 'Janeiro'),
    (2, 'Fevereiro'),
    (3, 'Março'),
    (4, 'Abril'),
    (5, 'Maio'),
    (6, 'Junho'),
    (7, 'Julho'),
    (8, 'Agosto'),
    (9, 'Setembro'),
    (10, 'Outubro'),
    (11, 'Novembro'),
    (12, 'Dezembro'),
]


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = 'w-full px-4 py-2.5 rounded-lg border border-slate-300 bg-white text-slate-800 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none transition'
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = CHOICE_INPUT_CLASS + ' rounded'
            elif isinstance(field.widget, (forms.RadioSelect, forms.CheckboxSelectMultiple)):
                field.widget.attrs['class'] = CHOICE_INPUT_CLASS + ' rounded'
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs['class'] = css + ' min-h-[100px]'
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = css
            else:
                field.widget.attrs['class'] = css


class LoginForm(StyledFormMixin, AuthenticationForm):
    username = forms.CharField(label='Email ou NIF')
    password = forms.CharField(label='Palavra-passe', widget=forms.PasswordInput)

    def clean(self):
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')

        if username is not None and password:
            resolved_username = self._resolve_login(username)
            self.user_cache = authenticate(
                self.request,
                username=resolved_username,
                password=password,
            )
            if self.user_cache is None:
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data

    @staticmethod
    def _resolve_login(login_value):
        login_value = (login_value or '').strip()
        if not login_value:
            return login_value

        if '@' in login_value:
            user = User.objects.filter(email__iexact=login_value).first()
            if user:
                return user.username

        digits = ''.join(c for c in login_value if c.isdigit())
        if len(digits) == 9:
            user = User.objects.filter(username=digits).first()
            if user:
                return user.username
            driver = Driver.objects.filter(nif=digits).select_related('user').first()
            if driver and driver.user_id:
                return driver.user.username

        return login_value


class RegisterForm(StyledFormMixin, UserCreationForm):
    contracting_company = forms.ModelChoiceField(
        label='Nome da Empresa',
        queryset=ContractingCompany.objects.none(),
        empty_label='Selecionar empresa...',
    )
    email = forms.EmailField(label='Email')
    first_name = forms.CharField(label='Nome', max_length=150)
    last_name = forms.CharField(label='Apelido', max_length=150, required=False)
    phone = forms.CharField(label='Telefone', max_length=20, required=False)

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        companies = ContractingCompany.objects.filter(is_active=True).order_by('sort_order', 'name')
        self.fields['contracting_company'].queryset = companies
        if not companies.exists():
            self.fields['contracting_company'].disabled = True
            self.fields['contracting_company'].empty_label = 'Nenhuma empresa disponível — contacte o suporte'
        self.order_fields([
            'contracting_company',
            'first_name',
            'last_name',
            'username',
            'phone',
            'email',
            'password1',
            'password2',
        ])
        self.fields['username'].label = 'NIF'
        self.fields['username'].help_text = ''
        self.fields['username'].widget.attrs.update({
            'inputmode': 'numeric',
            'pattern': '[0-9]{9}',
            'maxlength': '9',
            'placeholder': '123456789',
            'autocomplete': 'username',
        })
        self.fields['password1'].help_text = 'Mínimo 8 caracteres.'
        self.fields['password2'].help_text = ''

    def clean_username(self):
        nif = ''.join(c for c in (self.cleaned_data.get('username') or '') if c.isdigit())
        if len(nif) != 9:
            raise forms.ValidationError('O NIF deve ter 9 dígitos.')
        if User.objects.filter(username=nif).exists():
            raise forms.ValidationError('Este NIF já está registado.')
        if Driver.objects.filter(nif=nif).exists():
            raise forms.ValidationError('Este NIF já está registado.')
        return nif

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


PLATE_PATTERN = re.compile(r'^[A-Z0-9]{2}-[A-Z0-9]{2}-[A-Z0-9]{2}$')


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fuel_type'].empty_label = 'Selecionar...'
        self.fields['plate'].widget.attrs.update({
            'placeholder': 'AB-12-CD',
            'maxlength': '8',
            'autocomplete': 'off',
            'class': (
                self.fields['plate'].widget.attrs.get('class', '')
                + ' uppercase tracking-wider font-mono'
            ).strip(),
        })

    @staticmethod
    def format_plate(value):
        compact = ''.join(c for c in (value or '').upper() if c.isalnum())
        if len(compact) != 6:
            return value
        return f'{compact[0:2]}-{compact[2:4]}-{compact[4:6]}'

    def clean_plate(self):
        compact = ''.join(
            c for c in self.cleaned_data.get('plate', '').upper() if c.isalnum()
        )
        if len(compact) != 6:
            raise forms.ValidationError('Use o formato XX-XX-XX (ex.: AB-12-CD).')
        plate = f'{compact[0:2]}-{compact[2:4]}-{compact[4:6]}'
        if not PLATE_PATTERN.match(plate):
            raise forms.ValidationError('Use o formato XX-XX-XX (ex.: AB-12-CD).')
        return plate


class DriverForm(StyledFormMixin, forms.ModelForm):
    create_account = forms.BooleanField(
        required=False, initial=True, label='Criar conta de acesso (login)'
    )
    password = forms.CharField(
        required=False, label='Palavra-passe', widget=forms.PasswordInput,
        help_text='Obrigatória ao criar conta. Utilizador de login: NIF.',
    )

    class Meta:
        model = Driver
        fields = ['name', 'nif', 'phone', 'license_number', 'is_active']
        labels = {
            'name': 'Nome',
            'nif': 'NIF',
            'phone': 'Telefone',
            'license_number': 'Carta de Condução',
            'is_active': 'Ativo',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs.update({
            'autofocus': True,
            'autocomplete': 'name',
        })
        self.fields['nif'].widget.attrs.update({
            'inputmode': 'numeric',
            'pattern': '[0-9]{9}',
            'maxlength': '9',
            'placeholder': '123456789',
            'autocomplete': 'off',
        })
        self.fields['phone'].widget.attrs['autocomplete'] = 'tel'
        self.fields['license_number'].widget.attrs['autocomplete'] = 'off'
        self.fields['password'].widget.attrs['autocomplete'] = 'new-password'

    def clean_nif(self):
        nif = self._normalize_nif(self.cleaned_data.get('nif', ''))
        if len(nif) != 9:
            raise forms.ValidationError('O NIF deve ter 9 dígitos.')
        qs = Driver.objects.filter(nif=nif)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Este NIF já está registado.')
        return nif

    def clean(self):
        cleaned = super().clean()
        nif = cleaned.get('nif')
        if cleaned.get('create_account'):
            if not cleaned.get('password') and not self.instance.pk:
                self.add_error('password', 'Indique uma palavra-passe.')
            if nif and User.objects.filter(username=nif).exclude(
                pk=self.instance.user_id if self.instance.user_id else None
            ).exists():
                self.add_error('nif', 'Este NIF já está a ser usado como utilizador.')
        return cleaned

    @staticmethod
    def _normalize_nif(value):
        return ''.join(c for c in (value or '') if c.isdigit())

    def save(self, commit=True):
        driver = super().save(commit=False)
        if hasattr(self, 'organization'):
            driver.organization = self.organization
        if commit:
            driver.save()
            self._create_user_account(driver)
        return driver

    def _create_user_account(self, driver):
        if not self.cleaned_data.get('create_account'):
            return
        username = driver.nif
        if driver.user:
            user = driver.user
            user.username = username
            if self.cleaned_data.get('password'):
                user.set_password(self.cleaned_data['password'])
            user.email = driver.email or user.email
            user.save()
            return
        if not self.cleaned_data.get('password'):
            return
        user = User.objects.create_user(
            username=username,
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


class CompanyRouteForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CompanyRoute
        fields = [
            'delivery_company', 'name', 'revenue_account', 'daily_rate_account',
            'price_per_stop', 'price_per_pudo', 'price_per_pickup', 'daily_rate',
            'notes', 'is_active',
        ]
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            'delivery_company': 'Empresa Contratante',
            'name': 'Nome / Código da Rota',
            'revenue_account': 'Plano de conta (Produtividade)',
            'daily_rate_account': 'Plano de conta (Diárias)',
            'price_per_stop': 'Preço por Parada (€)',
            'price_per_pudo': 'Preço por PUDO (€)',
            'price_per_pickup': 'Preço por Recolha (€)',
            'daily_rate': 'Diária por dia (€)',
            'notes': 'Observações',
            'is_active': 'Ativa',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('revenue_account', 'daily_rate_account'):
            field = self.fields[name]
            field.required = True
            field.empty_label = 'Seleccione...'

    def clean_revenue_account(self):
        account = self.cleaned_data.get('revenue_account')
        if not account:
            raise forms.ValidationError('Seleccione o plano de conta de produtividade.')
        if account.account_type != FinancialAccount.TYPE_REVENUE:
            raise forms.ValidationError('Seleccione um plano de conta do tipo Receita.')
        return account

    def clean_daily_rate_account(self):
        account = self.cleaned_data.get('daily_rate_account')
        if not account:
            raise forms.ValidationError('Seleccione o plano de conta das diárias.')
        if account.account_type != FinancialAccount.TYPE_REVENUE:
            raise forms.ValidationError('Seleccione um plano de conta do tipo Receita.')
        return account


class ProductionAssignForm(StyledFormMixin, forms.Form):
    SCHEDULE_DAY = 'day'
    SCHEDULE_MONTH = 'month'
    SCHEDULE_CHOICES = [
        (SCHEDULE_DAY, 'Um dia'),
        (SCHEDULE_MONTH, 'Mês inteiro'),
    ]

    company_route = forms.ModelChoiceField(
        queryset=CompanyRoute.objects.none(),
        label='Empresa / Rota',
    )
    driver = forms.ModelChoiceField(queryset=Driver.objects.none(), label='Motorista')
    vehicle = forms.ModelChoiceField(queryset=Vehicle.objects.none(), label='Veículo')
    schedule_mode = forms.ChoiceField(
        choices=SCHEDULE_CHOICES,
        initial=SCHEDULE_DAY,
        label='Agendar por',
        widget=forms.RadioSelect,
    )
    date = forms.DateField(
        required=False,
        label='Dia',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    schedule_month = forms.ChoiceField(
        choices=MONTH_CHOICES,
        required=False,
        label='Mês',
    )
    schedule_year = forms.ChoiceField(
        choices=[],
        required=False,
        label='Ano',
    )
    weekdays = forms.MultipleChoiceField(
        choices=WEEKDAY_LABELS,
        required=False,
        label='Dias da semana',
        widget=forms.CheckboxSelectMultiple,
        initial=list(DEFAULT_WEEKDAYS),
    )
    notes = forms.CharField(
        required=False,
        label='Observações',
        widget=forms.Textarea(attrs={'rows': 3}),
    )
    is_active = forms.BooleanField(required=False, initial=True, label='Ativa')
    replace_existing = forms.BooleanField(
        required=False,
        label='Substituir atribuições existentes sem dados registados',
    )
    confirm_step = forms.BooleanField(required=False, widget=forms.HiddenInput)
    continue_adding = forms.BooleanField(
        required=False,
        label='Continuar',
    )

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        if organization:
            routes = CompanyRoute.objects.filter(
                organization=organization, is_active=True
            ).select_related('delivery_company').order_by(
                'delivery_company__name', 'name'
            )
            self.fields['company_route'].queryset = routes
            self.fields['company_route'].label_from_instance = (
                lambda cr: f'{cr.delivery_company.name} — {cr.name}'
            )
            self.fields['driver'].queryset = Driver.objects.filter(
                organization=organization, is_active=True
            )
            self.fields['vehicle'].queryset = Vehicle.objects.filter(
                organization=organization, is_active=True
            )
        if not self.is_bound:
            today = timezone.localdate()
            self.fields['date'].initial = today
            self.fields['schedule_month'].initial = today.month
            self.fields['schedule_year'].initial = today.year

        today = timezone.localdate()
        year_choices = [(y, str(y)) for y in range(today.year - 1, today.year + 3)]
        self.fields['schedule_year'].choices = year_choices

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get('schedule_mode')
        if mode == self.SCHEDULE_DAY:
            if not cleaned.get('date'):
                self.add_error('date', 'Indique o dia.')
        elif mode == self.SCHEDULE_MONTH:
            if not cleaned.get('schedule_month'):
                self.add_error('schedule_month', 'Seleccione o mês.')
            if not cleaned.get('schedule_year'):
                self.add_error('schedule_year', 'Seleccione o ano.')
            if cleaned.get('schedule_month') and cleaned.get('schedule_year'):
                try:
                    date(int(cleaned['schedule_year']), int(cleaned['schedule_month']), 1)
                except (ValueError, TypeError):
                    self.add_error('schedule_month', 'Mês ou ano inválido.')
            if not cleaned.get('weekdays'):
                self.add_error('weekdays', 'Seleccione pelo menos um dia da semana.')
        return cleaned

    def get_target_dates(self):
        mode = self.cleaned_data['schedule_mode']
        if mode == self.SCHEDULE_DAY:
            return [self.cleaned_data['date']]
        year = int(self.cleaned_data['schedule_year'])
        month = int(self.cleaned_data['schedule_month'])
        return get_dates_for_month(year, month, self.cleaned_data['weekdays'])


class RouteForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Route
        fields = [
            'company_route', 'date', 'driver', 'vehicle', 'notes', 'is_active',
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            'company_route': 'Empresa / Rota',
            'date': 'Data',
            'driver': 'Motorista',
            'vehicle': 'Veículo',
            'notes': 'Observações',
            'is_active': 'Ativa',
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            qs = CompanyRoute.objects.filter(
                organization=organization, is_active=True
            ).select_related('delivery_company').order_by(
                'delivery_company__name', 'name'
            )
            self.fields['company_route'].queryset = qs
            self.fields['company_route'].label_from_instance = (
                lambda cr: f'{cr.delivery_company.name} — {cr.name}'
            )


class DailyComparisonForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = DailyComparison
        fields = [
            'route',
            'driver_stops', 'driver_pudo', 'driver_pickups',
            'company_stops', 'company_pudo', 'company_pickups',
            'notes',
        ]
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            'route': 'Rota',
            'driver_stops': 'Paradas (Seus Dados)',
            'driver_pudo': 'PUDO (Seus Dados)',
            'driver_pickups': 'Recolhas (Seus Dados)',
            'company_stops': 'Paradas (Empresa)',
            'company_pudo': 'PUDO (Empresa)',
            'company_pickups': 'Recolhas (Empresa)',
            'notes': 'Observações',
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.route_id:
            self.fields['route'].widget = forms.HiddenInput()
        elif organization:
            routes = Route.objects.filter(organization=organization, is_active=True)
            routes = routes.filter(comparison__isnull=True)
            self.fields['route'].queryset = routes.select_related(
                'driver', 'vehicle'
            ).order_by('-date', 'name')
            self.fields['route'].label_from_instance = lambda r: r.label

    def save(self, commit=True):
        comp = super().save(commit=False)
        comp.sync_from_route()
        if commit:
            comp.save()
        return comp


class FuelRecordForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FuelRecord
        fields = [
            'vehicle', 'driver', 'date', 'liters', 'price_per_liter',
            'total_cost', 'odometer', 'station', 'notes',
        ]
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
            'total_cost': 'Valor Total (€)',
            'odometer': 'Quilometragem',
            'station': 'Posto',
            'notes': 'Observações',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['liters'].required = False
        self.fields['price_per_liter'].required = False
        self.fields['total_cost'].required = True
        self.fields['total_cost'].widget.attrs.update({
            'step': '0.01',
            'inputmode': 'decimal',
        })
        if self.instance.pk and not self.data:
            if not self.instance.total_cost and self.instance.liters and self.instance.price_per_liter:
                self.initial['total_cost'] = (
                    self.instance.liters * self.instance.price_per_liter
                ).quantize(Decimal('0.01'))

    def clean_liters(self):
        liters = self.cleaned_data.get('liters')
        if liters is None:
            return None
        if liters < Decimal('0.01'):
            raise forms.ValidationError('Indique um valor positivo ou deixe em branco.')
        return liters

    def clean_price_per_liter(self):
        price = self.cleaned_data.get('price_per_liter')
        if price is None:
            return None
        if price < Decimal('0.001'):
            raise forms.ValidationError('Indique um valor positivo ou deixe em branco.')
        return price

    def clean_total_cost(self):
        total = self.cleaned_data.get('total_cost')
        if total is None:
            raise forms.ValidationError('Indique o valor total.')
        if total < Decimal('0.01'):
            raise forms.ValidationError('O valor total deve ser superior a zero.')
        return total


class ExpenseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['account', 'vehicle', 'date', 'description', 'amount', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }
        labels = {
            'account': 'Plano de conta',
            'vehicle': 'Veículo',
            'date': 'Data',
            'description': 'Descrição',
            'amount': 'Valor (€)',
            'notes': 'Observações',
        }


class RevenueForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Revenue
        fields = ['account', 'vehicle', 'date', 'description', 'amount', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }
        labels = {
            'account': 'Plano de conta',
            'vehicle': 'Veículo',
            'date': 'Data',
            'description': 'Descrição',
            'amount': 'Valor (€)',
            'notes': 'Observações',
        }


class SubscriptionContractForm(StyledFormMixin, forms.Form):
    def __init__(self, *args, tariff=None, **kwargs):
        self.tariff = tariff
        super().__init__(*args, **kwargs)
        if tariff:
            self.fields['contracted_routes'].help_text = (
                f'O plano base ({tariff.price_first_route:.2f} €/mês) inclui '
                f'{tariff.included_routes} rotas. Cada rota adicional: '
                f'{tariff.price_additional_route:.2f} €/mês.'
            )

    contracted_routes = forms.IntegerField(
        label='Quantidade de rotas',
        min_value=1,
        widget=forms.NumberInput(attrs={'min': '1', 'step': '1'}),
    )
    payment_method = forms.ChoiceField(
        label='Forma de pagamento',
        choices=Subscription.PAYMENT_METHOD_CHOICES,
        widget=forms.RadioSelect,
    )

    def clean_contracted_routes(self):
        routes = self.cleaned_data['contracted_routes']
        if routes < 1:
            raise forms.ValidationError('Indique pelo menos uma rota.')
        return routes


class RouteAdditionRequestForm(StyledFormMixin, forms.Form):
    additional_routes = forms.IntegerField(
        label='Rotas adicionais a contratar',
        min_value=1,
        widget=forms.NumberInput(attrs={'min': '1', 'step': '1'}),
        help_text='Após confirmação do pagamento proporcional, poderá registar as novas rotas no catálogo.',
    )

    def clean_additional_routes(self):
        value = self.cleaned_data['additional_routes']
        if value < 1:
            raise forms.ValidationError('Indique pelo menos uma rota adicional.')
        return value


class FinancialAccountForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FinancialAccount
        fields = ['name', 'account_type', 'color']
        labels = {
            'name': 'Nome',
            'account_type': 'Tipo',
            'color': 'Cor',
        }
        widgets = {
            'color': forms.TextInput(attrs={'type': 'color'}),
        }


class RateConfigForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = RateConfig
        fields = ['price_per_stop', 'price_per_pudo', 'price_per_pickup']


class DeliveryCompanyForm(StyledFormMixin, forms.ModelForm):
    contracting_company = forms.ModelChoiceField(
        label='Nome',
        queryset=ContractingCompany.objects.none(),
        empty_label='Selecionar empresa...',
    )

    class Meta:
        model = DeliveryCompany
        fields = ['contact_email', 'contact_phone', 'notes', 'is_active']

    def __init__(self, *args, organization=None, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)
        qs = ContractingCompany.objects.filter(is_active=True).order_by('sort_order', 'name')
        if organization and not self.instance.pk:
            existing_names = DeliveryCompany.objects.filter(
                organization=organization,
            ).values_list('name', flat=True)
            qs = qs.exclude(name__in=existing_names)
        elif organization and self.instance.pk:
            current = ContractingCompany.objects.filter(name=self.instance.name).first()
            if current:
                self.fields['contracting_company'].initial = current.pk
        self.fields['contracting_company'].queryset = qs
        if not qs.exists() and not self.instance.pk:
            self.fields['contracting_company'].disabled = True
            self.fields['contracting_company'].empty_label = 'Nenhuma empresa disponível'
        self.order_fields([
            'contracting_company',
            'contact_email',
            'contact_phone',
            'notes',
            'is_active',
        ])

    def clean_contracting_company(self):
        company = self.cleaned_data['contracting_company']
        if not self.organization:
            return company
        qs = DeliveryCompany.objects.filter(
            organization=self.organization,
            name=company.name,
        )
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Esta empresa já está registada.')
        return company

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.name = self.cleaned_data['contracting_company'].name
        if commit:
            instance.save()
        return instance


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
