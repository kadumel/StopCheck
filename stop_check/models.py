from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class Organization(models.Model):
    name = models.CharField('Nome da Empresa', max_length=200)
    nif = models.CharField('NIF', max_length=20, blank=True)
    email = models.EmailField()
    phone = models.CharField('Telefone', max_length=20, blank=True)
    address = models.TextField('Morada', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Organização'
        verbose_name_plural = 'Organizações'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def vehicle_count(self):
        return self.vehicles.filter(is_active=True).count()

    @property
    def route_count(self):
        return self.company_routes.filter(is_active=True).count()

    @property
    def monthly_subscription(self):
        subscription = getattr(self, 'subscription', None)
        if not subscription:
            return Subscription.calculate_price(0)
        routes = subscription.billable_route_count
        return Subscription.calculate_price(routes)


class UserProfile(models.Model):
    ROLE_ADMIN = 'admin'
    ROLE_MANAGER = 'manager'
    ROLE_DRIVER = 'driver'
    ROLE_CHOICES = [
        (ROLE_ADMIN, 'Administrador'),
        (ROLE_MANAGER, 'Gestor'),
        (ROLE_DRIVER, 'Motorista'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='members'
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_MANAGER)
    phone = models.CharField('Telefone', max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Perfil de Utilizador'
        verbose_name_plural = 'Perfis de Utilizador'

    def __str__(self):
        return f'{self.user.get_full_name() or self.user.username} ({self.organization.name})'

    @property
    def is_admin(self):
        return self.role == self.ROLE_ADMIN

    @property
    def is_manager(self):
        return self.role in (self.ROLE_ADMIN, self.ROLE_MANAGER)

    @property
    def is_driver(self):
        return self.role == self.ROLE_DRIVER


class SubscriptionTariff(models.Model):
    """Tarifas e dados de pagamento da assinatura."""
    price_first_route = models.DecimalField(
        '1ª rota (€/mês)', max_digits=8, decimal_places=2, default=Decimal('20.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    price_additional_route = models.DecimalField(
        'Rota adicional (€/mês)', max_digits=8, decimal_places=2, default=Decimal('5.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    mbway_phone = models.CharField('Número MB Way', max_length=20, blank=True)
    iban = models.CharField('IBAN', max_length=34, blank=True)
    iban_holder = models.CharField('Titular da conta', max_length=200, blank=True)
    payment_notification_email = models.EmailField(
        'Email para avisos de pagamento', blank=True,
        help_text='Recebe alerta quando um cliente informa que pagou.',
    )

    class Meta:
        verbose_name = 'Tarifa de Assinatura'
        verbose_name_plural = 'Tarifa de Assinatura'

    def __str__(self):
        return 'Tarifas da assinatura'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Subscription(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_TRIAL = 'trial'
    STATUS_PENDING = 'pending'
    STATUS_SUSPENDED = 'suspended'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Ativa'),
        (STATUS_TRIAL, 'Período Experimental'),
        (STATUS_PENDING, 'Pagamento Pendente'),
        (STATUS_SUSPENDED, 'Suspensa'),
        (STATUS_CANCELLED, 'Cancelada'),
    ]

    PAYMENT_MBWAY = 'mbway'
    PAYMENT_TRANSFER = 'transfer'
    PAYMENT_METHOD_CHOICES = [
        (PAYMENT_MBWAY, 'MB Way'),
        (PAYMENT_TRANSFER, 'Transferência bancária'),
    ]

    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name='subscription'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_TRIAL)
    start_date = models.DateField(default=timezone.now)
    contracted_routes = models.PositiveIntegerField(
        'Rotas contratadas', null=True, blank=True,
    )
    payment_method = models.CharField(
        'Forma de pagamento', max_length=20, choices=PAYMENT_METHOD_CHOICES, blank=True,
    )
    payment_reported_at = models.DateTimeField(
        'Pagamento informado em', null=True, blank=True,
    )
    stripe_customer_id = models.CharField(max_length=255, blank=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    last_payment_date = models.DateField(null=True, blank=True)
    notes = models.TextField('Observações', blank=True)

    class Meta:
        verbose_name = 'Assinatura'
        verbose_name_plural = 'Assinaturas'

    def __str__(self):
        return f'{self.organization.name} - {self.get_status_display()}'

    @property
    def billable_route_count(self):
        if self.contracted_routes:
            return self.contracted_routes
        return self.organization.route_count

    @classmethod
    def calculate_price(cls, route_count):
        tariff = SubscriptionTariff.get()
        if route_count <= 0:
            return tariff.price_first_route
        return tariff.price_first_route + (route_count - 1) * tariff.price_additional_route

    @property
    def monthly_price(self):
        return self.calculate_price(self.billable_route_count)

    @property
    def is_unlimited_trial(self):
        return self.status == self.STATUS_TRIAL

    @property
    def payment_reported(self):
        return self.payment_reported_at is not None


class RateConfig(models.Model):
    """Tarifas por operação para cálculo de receita."""
    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name='rate_config'
    )
    price_per_stop = models.DecimalField(
        'Preço por Parada (€)', max_digits=8, decimal_places=2, default=Decimal('1.50')
    )
    price_per_pudo = models.DecimalField(
        'Preço por PUDO (€)', max_digits=8, decimal_places=2, default=Decimal('0.80')
    )
    price_per_pickup = models.DecimalField(
        'Preço por Recolha (€)', max_digits=8, decimal_places=2, default=Decimal('1.20')
    )

    class Meta:
        verbose_name = 'Configuração de Tarifas'
        verbose_name_plural = 'Configurações de Tarifas'

    def __str__(self):
        return f'Tarifas - {self.organization.name}'


class Vehicle(models.Model):
    FUEL_GASOLINA = 'gasolina'
    FUEL_GASOLEO = 'gasoleo'
    FUEL_GAS_NATURAL = 'gas_natural'
    FUEL_ELETRICO = 'eletrico'
    FUEL_CHOICES = [
        (FUEL_GASOLINA, 'Gasolina'),
        (FUEL_GASOLEO, 'Gasóleo'),
        (FUEL_GAS_NATURAL, 'Gás Natural'),
        (FUEL_ELETRICO, 'Elétrico'),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='vehicles'
    )
    plate = models.CharField('Matrícula', max_length=20)
    brand = models.CharField('Marca', max_length=50, blank=True)
    model = models.CharField('Modelo', max_length=50, blank=True)
    year = models.PositiveIntegerField('Ano', null=True, blank=True)
    fuel_type = models.CharField(
        'Combustível', max_length=20, choices=FUEL_CHOICES, blank=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Veículo'
        verbose_name_plural = 'Veículos'
        ordering = ['plate']
        unique_together = ['organization', 'plate']

    def __str__(self):
        return self.plate

    def get_delete_blockers(self):
        """Motivos que impedem eliminar o veículo (referências noutras tabelas)."""
        blockers = []
        routes = self.routes.count()
        if routes:
            blockers.append(f'{routes} atribuição(ões) de rota em produção')
        comparisons = self.comparisons.count()
        if comparisons:
            blockers.append(f'{comparisons} comparação(ões) diária(s)')
        fuel = self.fuel_records.count()
        if fuel:
            blockers.append(f'{fuel} registo(s) de combustível')
        expenses = self.expenses.count()
        if expenses:
            blockers.append(f'{expenses} despesa(s)')
        events = self.stop_events.count()
        if events:
            blockers.append(f'{events} evento(s) registado(s) pelo motorista')
        drivers = self.default_drivers.count()
        if drivers:
            blockers.append(f'{drivers} motorista(s) com este veículo padrão')
        return blockers

    @property
    def can_be_deleted(self):
        return not self.get_delete_blockers()


class Driver(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='drivers'
    )
    user = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='driver_profile'
    )
    name = models.CharField('Nome', max_length=200)
    nif = models.CharField('NIF', max_length=9, unique=True)
    email = models.EmailField(blank=True)
    phone = models.CharField('Telefone', max_length=20, blank=True)
    license_number = models.CharField('Carta de Condução', max_length=30, blank=True)
    default_vehicle = models.ForeignKey(
        Vehicle, on_delete=models.SET_NULL, null=True, blank=True, related_name='default_drivers'
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Motorista'
        verbose_name_plural = 'Motoristas'
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_delete_blockers(self):
        blockers = []
        routes = self.routes.count()
        if routes:
            blockers.append(f'{routes} atribuição(ões) de rota em produção')
        comparisons = self.comparisons.count()
        if comparisons:
            blockers.append(f'{comparisons} comparação(ões) diária(s)')
        fuel = self.fuel_records.count()
        if fuel:
            blockers.append(f'{fuel} registo(s) de combustível')
        events = self.stop_events.count()
        if events:
            blockers.append(f'{events} evento(s) registado(s) na app')
        return blockers

    @property
    def can_be_deleted(self):
        return not self.get_delete_blockers()


class CompanyRoute(models.Model):
    """Catálogo de rotas de uma empresa contratante (ex: LIS-01, POR-Norte)."""
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='company_routes'
    )
    delivery_company = models.ForeignKey(
        'DeliveryCompany', on_delete=models.CASCADE, related_name='company_routes',
    )
    name = models.CharField('Nome / Código da Rota', max_length=100)
    price_per_stop = models.DecimalField(
        'Preço por Parada (€)', max_digits=8, decimal_places=2, default=Decimal('1.50'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    price_per_pudo = models.DecimalField(
        'Preço por PUDO (€)', max_digits=8, decimal_places=2, default=Decimal('0.80'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    price_per_pickup = models.DecimalField(
        'Preço por Recolha (€)', max_digits=8, decimal_places=2, default=Decimal('1.20'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    daily_rate = models.DecimalField(
        'Diária (€)', max_digits=8, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    revenue_account = models.ForeignKey(
        'FinancialAccount', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='company_routes', verbose_name='Plano de conta (Receita)',
        limit_choices_to={'account_type': 'revenue'},
    )
    notes = models.TextField('Observações', blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Rota da Empresa'
        verbose_name_plural = 'Rotas da Empresa'
        ordering = ['delivery_company__name', 'name']
        unique_together = ['organization', 'delivery_company', 'name']

    def __str__(self):
        return f'{self.delivery_company.name} — {self.name}'

    def get_delete_blockers(self):
        assignments = self.assignments.count()
        if assignments:
            return [f'{assignments} atribuição(ões) em produção']
        return []

    @property
    def can_be_deleted(self):
        return not self.get_delete_blockers()


class Route(models.Model):
    """Atribuição diária: execução de uma rota com motorista e veículo específicos."""
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='routes'
    )
    company_route = models.ForeignKey(
        CompanyRoute, on_delete=models.PROTECT, related_name='assignments',
        null=True, blank=True,
    )
    name = models.CharField('Nome / Código da Rota', max_length=100)
    date = models.DateField('Data')
    driver = models.ForeignKey(
        Driver, on_delete=models.CASCADE, related_name='routes'
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.PROTECT, related_name='routes'
    )
    delivery_company = models.ForeignKey(
        'DeliveryCompany', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='routes',
    )
    notes = models.TextField('Observações', blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Atribuição de Rota'
        verbose_name_plural = 'Atribuições de Rota'
        ordering = ['-date', 'name']
        unique_together = ['organization', 'name', 'date']

    def __str__(self):
        return f'{self.name} — {self.date.strftime("%d/%m/%Y")}'

    def sync_from_company_route(self):
        if self.company_route:
            self.name = self.company_route.name
            self.delivery_company = self.company_route.delivery_company
            self.organization = self.company_route.organization

    def save(self, *args, **kwargs):
        self.sync_from_company_route()
        super().save(*args, **kwargs)

    @property
    def label(self):
        company = self.delivery_company.name if self.delivery_company else '—'
        return (
            f'{company} / {self.name} ({self.date.strftime("%d/%m/%Y")})'
            f' — {self.driver.name} / {self.vehicle.plate}'
        )

    @property
    def can_be_deleted(self):
        from stop_check.services.production_service import assignment_has_production_data
        return not assignment_has_production_data(self)


class DailyComparison(models.Model):
    """Comparativo diário: dados do motorista vs dados reportados pela empresa."""
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='comparisons'
    )
    route = models.OneToOneField(
        Route, on_delete=models.CASCADE, related_name='comparison', null=True, blank=True
    )
    driver = models.ForeignKey(
        Driver, on_delete=models.CASCADE, related_name='comparisons'
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.SET_NULL, null=True, blank=True, related_name='comparisons'
    )
    date = models.DateField('Data')

    # Dados do motorista (fonte principal)
    driver_stops = models.PositiveIntegerField('Paradas (Motorista)', default=0)
    driver_pudo = models.PositiveIntegerField('PUDO (Motorista)', default=0)
    driver_pickups = models.PositiveIntegerField('Recolhas (Motorista)', default=0)

    # Dados reportados pela empresa contratante
    company_stops = models.PositiveIntegerField('Paradas (Empresa)', default=0)
    company_pudo = models.PositiveIntegerField('PUDO (Empresa)', default=0)
    company_pickups = models.PositiveIntegerField('Recolhas (Empresa)', default=0)

    DATA_PENDING = 'pending'
    DATA_FILLED = 'filled'
    DATA_STATUS_CHOICES = [
        (DATA_PENDING, 'Pendente'),
        (DATA_FILLED, 'Registado'),
    ]

    driver_data_status = models.CharField(
        'Estado dados motorista', max_length=20,
        choices=DATA_STATUS_CHOICES, default=DATA_PENDING,
    )
    driver_data_locked = models.BooleanField(
        'Dados motorista bloqueados', default=False,
        help_text='Quando activo, o motorista não pode alterar os seus dados.',
    )
    driver_submitted_at = models.DateTimeField(
        'Registo motorista concluído em', null=True, blank=True,
    )
    company_data_status = models.CharField(
        'Estado dados empresa', max_length=20,
        choices=DATA_STATUS_CHOICES, default=DATA_PENDING,
    )

    notes = models.TextField('Observações', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Comparação Diária'
        verbose_name_plural = 'Comparações Diárias'
        ordering = ['-date', '-created_at']

    def __str__(self):
        if self.route:
            return f'{self.route.name} — {self.date.strftime("%d/%m/%Y")}'
        return f'{self.driver.name} - {self.date.strftime("%d/%m/%Y")}'

    def sync_from_route(self):
        if self.route:
            self.driver = self.route.driver
            self.vehicle = self.route.vehicle
            self.date = self.route.date
            self.organization = self.route.organization

    def refresh_data_statuses(self):
        self.driver_data_status = (
            self.DATA_FILLED if self.driver_total > 0 else self.DATA_PENDING
        )
        self.company_data_status = (
            self.DATA_FILLED if self.company_total > 0 else self.DATA_PENDING
        )

    @property
    def driver_can_edit(self):
        return not self.driver_data_locked

    def save(self, *args, **kwargs):
        self.refresh_data_statuses()
        super().save(*args, **kwargs)

    @property
    def driver_total(self):
        return self.driver_stops + self.driver_pudo + self.driver_pickups

    @property
    def company_total(self):
        return self.company_stops + self.company_pudo + self.company_pickups

    @property
    def diff_stops(self):
        return self.driver_stops - self.company_stops

    @property
    def diff_pudo(self):
        return self.driver_pudo - self.company_pudo

    @property
    def diff_pickups(self):
        return self.driver_pickups - self.company_pickups

    @property
    def diff_total(self):
        return self.driver_total - self.company_total

    @property
    def has_discrepancy(self):
        return (
            self.diff_stops != 0
            or self.diff_pudo != 0
            or self.diff_pickups != 0
        )

    def get_rates(self):
        from .utils import get_comparison_rates
        return get_comparison_rates(self)

    def calculate_revenue(self, rates=None):
        rates = rates or self.get_rates()
        return (
            self.driver_stops * rates.price_per_stop
            + self.driver_pudo * rates.price_per_pudo
            + self.driver_pickups * rates.price_per_pickup
            + rates.daily_rate
        )

    def calculate_company_revenue(self, rates=None):
        rates = rates or self.get_rates()
        return (
            self.company_stops * rates.price_per_stop
            + self.company_pudo * rates.price_per_pudo
            + self.company_pickups * rates.price_per_pickup
            + rates.daily_rate
        )

    def calculate_diff_amounts(self, rates=None):
        """Valor monetário da diferença por tipo (tarifas da rota)."""
        rates = rates or self.get_rates()
        return {
            'stops': Decimal(self.diff_stops) * rates.price_per_stop,
            'pudo': Decimal(self.diff_pudo) * rates.price_per_pudo,
            'pickups': Decimal(self.diff_pickups) * rates.price_per_pickup,
        }

    def calculate_diff_revenue(self, rates=None):
        amounts = self.calculate_diff_amounts(rates)
        return amounts['stops'] + amounts['pudo'] + amounts['pickups']

    def get_diff_amounts(self):
        return self.calculate_diff_amounts()

    def get_diff_revenue_total(self):
        amounts = self.get_diff_amounts()
        return amounts['stops'] + amounts['pudo'] + amounts['pickups']


class FuelRecord(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='fuel_records'
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.CASCADE, related_name='fuel_records'
    )
    driver = models.ForeignKey(
        Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name='fuel_records'
    )
    date = models.DateField('Data')
    liters = models.DecimalField(
        'Litros', max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))]
    )
    price_per_liter = models.DecimalField(
        'Preço/Litro (€)', max_digits=6, decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))]
    )
    total_cost = models.DecimalField(
        'Valor Total (€)', max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    odometer = models.PositiveIntegerField('Quilometragem', null=True, blank=True)
    station = models.CharField('Posto', max_length=100, blank=True)
    notes = models.TextField('Observações', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Registo de Combustível'
        verbose_name_plural = 'Registos de Combustível'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f'{self.vehicle.plate} - {self.date.strftime("%d/%m/%Y")}'


class FinancialAccount(models.Model):
    TYPE_EXPENSE = 'expense'
    TYPE_REVENUE = 'revenue'
    TYPE_CHOICES = [
        (TYPE_EXPENSE, 'Despesa'),
        (TYPE_REVENUE, 'Receita'),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='financial_accounts'
    )
    name = models.CharField('Nome', max_length=100)
    color = models.CharField('Cor', max_length=7, default='#64748b')
    account_type = models.CharField(
        'Tipo', max_length=10, choices=TYPE_CHOICES, default=TYPE_EXPENSE,
    )

    class Meta:
        verbose_name = 'Plano de Conta'
        verbose_name_plural = 'Plano de Contas'
        unique_together = ['organization', 'name']

    def __str__(self):
        return self.name

    def get_delete_blockers(self):
        blockers = []
        expenses = self.expenses.count()
        if expenses:
            blockers.append(f'{expenses} despesa(s)')
        revenues = self.revenues.count()
        if revenues:
            blockers.append(f'{revenues} receita(s)')
        routes = self.company_routes.count()
        if routes:
            blockers.append(f'{routes} rota(s) no catálogo')
        return blockers

    @property
    def can_be_deleted(self):
        return not self.get_delete_blockers()


class Expense(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='expenses'
    )
    account = models.ForeignKey(
        FinancialAccount, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='expenses', verbose_name='Plano de conta',
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses'
    )
    date = models.DateField('Data')
    description = models.CharField('Descrição', max_length=255)
    amount = models.DecimalField(
        'Valor (€)', max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    notes = models.TextField('Observações', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Despesa'
        verbose_name_plural = 'Despesas'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f'{self.description} - {self.amount}€'


class Revenue(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='revenues'
    )
    comparison = models.OneToOneField(
        DailyComparison, on_delete=models.CASCADE, related_name='revenue_entry',
        null=True, blank=True,
    )
    account = models.ForeignKey(
        FinancialAccount, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='revenues', verbose_name='Plano de conta',
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.SET_NULL, null=True, blank=True, related_name='revenues',
    )
    route = models.ForeignKey(
        Route, on_delete=models.SET_NULL, null=True, blank=True, related_name='revenues',
    )
    date = models.DateField('Data')
    description = models.CharField('Descrição', max_length=255)
    amount = models.DecimalField(
        'Valor (€)', max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    notes = models.TextField('Observações', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Receita'
        verbose_name_plural = 'Receitas'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f'{self.description} - {self.amount}€'

    @property
    def is_manual(self):
        return self.comparison_id is None

    @property
    def display_vehicle(self):
        if self.vehicle_id:
            return self.vehicle
        if self.comparison_id and self.comparison.vehicle_id:
            return self.comparison.vehicle
        if self.route_id and self.route.vehicle_id:
            return self.route.vehicle
        return None


class DeliveryCompany(models.Model):
    """Empresa contratante de entregas (ex: GLS, DPD, etc.)."""
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='delivery_companies'
    )
    name = models.CharField('Nome', max_length=200)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField('Telefone', max_length=20, blank=True)
    notes = models.TextField('Observações', blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Empresa de Entrega'
        verbose_name_plural = 'Empresas de Entrega'
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_delete_blockers(self):
        blockers = []
        catalog = self.company_routes.count()
        if catalog:
            blockers.append(f'{catalog} rota(s) no catálogo (elimine-as primeiro)')
        assignments = self.routes.count()
        if assignments:
            blockers.append(f'{assignments} atribuição(ões) em produção')
        imports = self.imports.count()
        if imports:
            blockers.append(f'{imports} importação(ões) de ficheiros')
        return blockers

    @property
    def can_be_deleted(self):
        return not self.get_delete_blockers()


class StopEvent(models.Model):
    """Registo individual de operação em tempo real (app mobile)."""
    TYPE_STOP = 'stop'
    TYPE_PUDO = 'pudo'
    TYPE_PICKUP = 'pickup'
    TYPE_CHOICES = [
        (TYPE_STOP, 'Parada'),
        (TYPE_PUDO, 'PUDO'),
        (TYPE_PICKUP, 'Recolha'),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='stop_events'
    )
    driver = models.ForeignKey(
        Driver, on_delete=models.CASCADE, related_name='stop_events'
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.SET_NULL, null=True, blank=True, related_name='stop_events'
    )
    route = models.ForeignKey(
        Route, on_delete=models.SET_NULL, null=True, blank=True, related_name='stop_events'
    )
    event_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    recorded_at = models.DateTimeField(default=timezone.now)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = 'Evento de Parada'
        verbose_name_plural = 'Eventos de Parada'
        ordering = ['-recorded_at']

    def __str__(self):
        return f'{self.driver.name} — {self.get_event_type_display()} — {self.recorded_at:%d/%m %H:%M}'


class ImportBatch(models.Model):
    """Histórico de importação de ficheiros da empresa contratante."""
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pendente'),
        (STATUS_PROCESSING, 'A processar'),
        (STATUS_COMPLETED, 'Concluído'),
        (STATUS_FAILED, 'Falhou'),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='import_batches'
    )
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='import_batches'
    )
    delivery_company = models.ForeignKey(
        DeliveryCompany, on_delete=models.SET_NULL, null=True, blank=True, related_name='imports'
    )
    file = models.FileField('Ficheiro', upload_to='imports/%Y/%m/')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    rows_processed = models.PositiveIntegerField(default=0)
    rows_updated = models.PositiveIntegerField(default=0)
    rows_failed = models.PositiveIntegerField(default=0)
    error_log = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Importação'
        verbose_name_plural = 'Importações'
        ordering = ['-created_at']

    def __str__(self):
        return f'Importação {self.pk} — {self.organization.name} — {self.get_status_display()}'


class EmailVerification(models.Model):
    """Verificação de email pendente no registo de empresa."""
    email = models.EmailField(db_index=True)
    code_hash = models.CharField(max_length=128)
    payload = models.JSONField()
    expires_at = models.DateTimeField()
    is_verified = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Verificação de Email'
        verbose_name_plural = 'Verificações de Email'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.email} — {"verificado" if self.is_verified else "pendente"}'

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at
