from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import (
    DailyComparison,
    DeliveryCompany,
    Driver,
    EmailVerification,
    Expense,
    ExpenseCategory,
    FuelRecord,
    ImportBatch,
    Organization,
    RateConfig,
    StopEvent,
    Subscription,
    UserProfile,
    Vehicle,
)


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False


class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'phone', 'is_active', 'created_at']
    search_fields = ['name', 'email']


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['organization', 'status', 'start_date', 'monthly_price']
    list_filter = ['status']


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ['plate', 'organization', 'brand', 'model', 'is_active']
    list_filter = ['organization', 'is_active']


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'phone', 'is_active']
    list_filter = ['organization', 'is_active']


@admin.register(DailyComparison)
class DailyComparisonAdmin(admin.ModelAdmin):
    list_display = ['date', 'driver', 'driver_total', 'company_total', 'diff_total', 'organization']
    list_filter = ['organization', 'date']
    date_hierarchy = 'date'


@admin.register(FuelRecord)
class FuelRecordAdmin(admin.ModelAdmin):
    list_display = ['date', 'vehicle', 'liters', 'total_cost', 'organization']
    list_filter = ['organization', 'date']


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ['date', 'description', 'amount', 'category', 'organization']
    list_filter = ['organization', 'category']


admin.site.register(RateConfig)
admin.site.register(ExpenseCategory)
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
