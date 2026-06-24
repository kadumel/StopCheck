from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils import timezone

from .models import (
    CompanyRoute,
    ContractingCompany,
    DailyComparison,
    DeliveryCompany,
    Driver,
    EmailVerification,
    Expense,
    FinancialAccount,
    FuelRecord,
    Revenue,
    ImportBatch,
    Organization,
    RateConfig,
    Route,
    RouteAdditionRequest,
    StopEvent,
    Subscription,
    SubscriptionInvoice,
    SubscriptionTariff,
    UserProfile,
    Vehicle,
)
from .services.billing_service import mark_invoice_paid


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False


class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(ContractingCompany)
class ContractingCompanyAdmin(admin.ModelAdmin):
    list_display = ['name', 'sort_order', 'is_active']
    list_editable = ['sort_order', 'is_active']
    search_fields = ['name']
    ordering = ['sort_order', 'name']


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'contracting_company', 'email', 'phone', 'is_active', 'created_at']
    search_fields = ['name', 'email']


@admin.register(SubscriptionTariff)
class SubscriptionTariffAdmin(admin.ModelAdmin):
    list_display = [
        'trial_days', 'included_routes', 'price_first_route', 'price_additional_route',
        'payment_due_day', 'mbway_phone', 'iban', 'payment_notification_email',
    ]

    def has_add_permission(self, request):
        return not SubscriptionTariff.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = [
        'organization', 'status', 'contracted_routes', 'payment_method',
        'trial_end_date', 'payment_reported_at', 'start_date', 'monthly_price',
    ]
    list_filter = ['status', 'payment_method']
    readonly_fields = ['payment_reported_at']
    actions = ['activate_subscriptions']

    @admin.action(description='Activar assinaturas seleccionadas')
    def activate_subscriptions(self, request, queryset):
        updated = 0
        for subscription in queryset:
            pending = subscription.invoices.filter(
                status=SubscriptionInvoice.STATUS_PENDING,
            ).order_by('period_start').first()
            if pending:
                mark_invoice_paid(pending)
                updated += 1
            else:
                subscription.status = Subscription.STATUS_ACTIVE
                subscription.last_payment_date = timezone.now().date()
                subscription.save(update_fields=['status', 'last_payment_date'])
                updated += 1
        self.message_user(request, f'{updated} assinatura(s) activada(s).')


@admin.register(SubscriptionInvoice)
class SubscriptionInvoiceAdmin(admin.ModelAdmin):
    list_display = [
        'organization_name', 'invoice_type', 'amount', 'period_start',
        'period_end', 'due_date', 'status', 'payment_reported_at', 'paid_at',
    ]
    list_filter = ['status', 'invoice_type', 'due_date']
    search_fields = ['subscription__organization__name', 'subscription__organization__email']
    readonly_fields = ['generated_at', 'payment_reported_at', 'paid_at']
    actions = ['mark_as_paid']

    @admin.display(description='Organização')
    def organization_name(self, obj):
        return obj.organization.name

    @admin.action(description='Marcar como pago')
    def mark_as_paid(self, request, queryset):
        count = 0
        for invoice in queryset.exclude(status=SubscriptionInvoice.STATUS_PAID):
            mark_invoice_paid(invoice)
            count += 1
        self.message_user(request, f'{count} cobrança(s) marcada(s) como paga(s).')


@admin.register(RouteAdditionRequest)
class RouteAdditionRequestAdmin(admin.ModelAdmin):
    list_display = [
        'organization_name', 'additional_routes', 'status', 'invoice_amount', 'created_at',
    ]
    list_filter = ['status']
    search_fields = ['subscription__organization__name']
    readonly_fields = ['created_at']

    @admin.display(description='Organização')
    def organization_name(self, obj):
        return obj.organization.name

    @admin.display(description='Valor')
    def invoice_amount(self, obj):
        return obj.invoice.amount if obj.invoice_id else '—'


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ['plate', 'organization', 'brand', 'model', 'fuel_type', 'is_active']
    list_filter = ['organization', 'fuel_type', 'is_active']


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ['name', 'nif', 'organization', 'phone', 'is_active']
    list_filter = ['organization', 'is_active']


@admin.register(CompanyRoute)
class CompanyRouteAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'delivery_company', 'revenue_account', 'daily_rate_account',
        'price_per_stop', 'price_per_pudo', 'price_per_pickup', 'daily_rate',
        'organization', 'is_active', 'pending_payment',
    ]
    list_filter = ['organization', 'delivery_company', 'is_active', 'pending_payment']


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ['name', 'company_route', 'date', 'driver', 'vehicle', 'organization', 'is_active']
    list_filter = ['organization', 'date', 'is_active']
    date_hierarchy = 'date'


@admin.register(DailyComparison)
class DailyComparisonAdmin(admin.ModelAdmin):
    list_display = ['date', 'route', 'driver', 'driver_total', 'company_total', 'diff_total', 'organization']
    list_filter = ['organization', 'date']
    date_hierarchy = 'date'


@admin.register(FuelRecord)
class FuelRecordAdmin(admin.ModelAdmin):
    list_display = ['date', 'vehicle', 'liters', 'total_cost', 'organization']
    list_filter = ['organization', 'date']


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ['date', 'description', 'amount', 'account', 'organization']
    list_filter = ['organization', 'account']


@admin.register(Revenue)
class RevenueAdmin(admin.ModelAdmin):
    list_display = ['date', 'description', 'amount', 'account', 'organization']
    list_filter = ['organization', 'account']
    date_hierarchy = 'date'


admin.site.register(RateConfig)
admin.site.register(FinancialAccount)
admin.site.register(DeliveryCompany)
admin.site.register(UserProfile)


@admin.register(StopEvent)
class StopEventAdmin(admin.ModelAdmin):
    list_display = ['recorded_at', 'driver', 'event_type', 'organization']
    list_filter = ['organization', 'event_type', 'recorded_at']


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ['pk', 'organization', 'status', 'rows_updated', 'rows_failed', 'created_at']
    list_filter = ['status', 'organization']


@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    list_display = ['email', 'is_verified', 'attempts', 'expires_at', 'created_at']
    list_filter = ['is_verified']
    readonly_fields = ['code_hash', 'payload', 'created_at']
