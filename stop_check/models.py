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
    def monthly_subscription(self):
        return Subscription.calculate_price(self.vehicle_count)


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


class Subscription(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_TRIAL = 'trial'
    STATUS_SUSPENDED = 'suspended'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Ativa'),
        (STATUS_TRIAL, 'Período Experimental'),
        (STATUS_SUSPENDED, 'Suspensa'),
        (STATUS_CANCELLED, 'Cancelada'),
    ]

    BASE_PRICE = Decimal('20.00')
    ADDITIONAL_VEHICLE_PRICE = Decimal('5.00')

    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name='subscription'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_TRIAL)
    start_date = models.DateField(default=timezone.now)
    trial_end_date = models.DateField(null=True, blank=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    last_payment_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Assinatura'
        verbose_name_plural = 'Assinaturas'

    def __str__(self):
        return f'{self.organization.name} - {self.get_status_display()}'

    @classmethod
    def calculate_price(cls, vehicle_count):
        if vehicle_count <= 0:
            return cls.BASE_PRICE
        return cls.BASE_PRICE + (vehicle_count - 1) * cls.ADDITIONAL_VEHICLE_PRICE

    @property
    def monthly_price(self):
        return self.calculate_price(self.organization.vehicle_count)


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
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='vehicles'
    )
    plate = models.CharField('Matrícula', max_length=20)
    brand = models.CharField('Marca', max_length=50, blank=True)
    model = models.CharField('Modelo', max_length=50, blank=True)
    year = models.PositiveIntegerField('Ano', null=True, blank=True)
    fuel_type = models.CharField('Combustível', max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Veículo'
        verbose_name_plural = 'Veículos'
        ordering = ['plate']
        unique_together = ['organization', 'plate']

    def __str__(self):
        return self.plate


class Driver(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='drivers'
    )
    user = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='driver_profile'
    )
    name = models.CharField('Nome', max_length=200)
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


class Route(models.Model):
    """Rota diária: serviço num dia com motorista e veículo específicos."""
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='routes'
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
        verbose_name = 'Rota'
        verbose_name_plural = 'Rotas'
        ordering = ['-date', 'name']
        unique_together = ['organization', 'name', 'date']

    def __str__(self):
        return f'{self.name} — {self.date.strftime("%d/%m/%Y")}'

    @property
    def label(self):
        return f'{self.name} ({self.date.strftime("%d/%m/%Y")}) — {self.driver.name} / {self.vehicle.plate}'


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

    def calculate_revenue(self, rate_config):
        return (
            self.driver_stops * rate_config.price_per_stop
            + self.driver_pudo * rate_config.price_per_pudo
            + self.driver_pickups * rate_config.price_per_pickup
        )

    def calculate_company_revenue(self, rate_config):
        return (
            self.company_stops * rate_config.price_per_stop
            + self.company_pudo * rate_config.price_per_pudo
            + self.company_pickups * rate_config.price_per_pickup
        )

    def calculate_diff_amounts(self, rate_config):
        """Valor monetário da diferença por tipo (tarifas da assinatura)."""
        return {
            'stops': Decimal(self.diff_stops) * rate_config.price_per_stop,
            'pudo': Decimal(self.diff_pudo) * rate_config.price_per_pudo,
            'pickups': Decimal(self.diff_pickups) * rate_config.price_per_pickup,
        }

    def calculate_diff_revenue(self, rate_config):
        amounts = self.calculate_diff_amounts(rate_config)
        return amounts['stops'] + amounts['pudo'] + amounts['pickups']

    def get_diff_amounts(self):
        from .utils import get_or_create_rate_config
        return self.calculate_diff_amounts(get_or_create_rate_config(self.organization))

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

    @property
    def total_cost(self):
        return self.liters * self.price_per_liter


class ExpenseCategory(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='expense_categories'
    )
    name = models.CharField('Nome', max_length=100)
    color = models.CharField('Cor', max_length=7, default='#64748b')

    class Meta:
        verbose_name = 'Categoria de Despesa'
        verbose_name_plural = 'Categorias de Despesas'
        unique_together = ['organization', 'name']

    def __str__(self):
        return self.name


class Expense(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='expenses'
    )
    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses'
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
