from django.urls import path

from . import views
from . import views_driver
from . import views_import
from . import views_payments

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('registar/', views.register_view, name='register'),

    path('comparacoes/', views.comparison_list, name='comparison_list'),
    path('comparacoes/nova/', views.comparison_create, name='comparison_create'),
    path('comparacoes/<int:pk>/editar/', views.comparison_edit, name='comparison_edit'),
    path('comparacoes/<int:pk>/eliminar/', views.comparison_delete, name='comparison_delete'),

    path('frota/', views.vehicle_list, name='vehicle_list'),
    path('frota/nova/', views.vehicle_create, name='vehicle_create'),
    path('frota/<int:pk>/editar/', views.vehicle_edit, name='vehicle_edit'),

    path('motoristas/', views.driver_list, name='driver_list'),
    path('motoristas/novo/', views.driver_create, name='driver_create'),
    path('motoristas/<int:pk>/editar/', views.driver_edit, name='driver_edit'),

    path('combustivel/', views.fuel_list, name='fuel_list'),
    path('combustivel/novo/', views.fuel_create, name='fuel_create'),
    path('combustivel/<int:pk>/editar/', views.fuel_edit, name='fuel_edit'),
    path('combustivel/<int:pk>/eliminar/', views.fuel_delete, name='fuel_delete'),

    path('despesas/', views.expense_list, name='expense_list'),
    path('despesas/nova/', views.expense_create, name='expense_create'),

    path('financeiro/', views.finance_view, name='finance'),
    path('assinatura/', views.subscription_view, name='subscription'),

    path('exportar/excel/', views.export_excel, name='export_excel'),
    path('exportar/pdf/', views.export_pdf, name='export_pdf'),

    # App mobile motorista
    path('motorista/', views_driver.driver_app, name='driver_app'),
    path('motorista/registar/', views_driver.driver_log_event, name='driver_log_event'),
    path('motorista/historico/', views_driver.driver_history, name='driver_history'),

    # Importação ficheiros empresa
    path('importar/', views_import.import_list, name='import_list'),
    path('importar/novo/', views_import.import_upload, name='import_upload'),
    path('importar/<int:pk>/', views_import.import_detail, name='import_detail'),
    path('empresas-entrega/', views_import.delivery_company_list, name='delivery_company_list'),
    path('empresas-entrega/nova/', views_import.delivery_company_create, name='delivery_company_create'),

    # Pagamentos Stripe
    path('pagamentos/checkout/', views_payments.stripe_checkout, name='stripe_checkout'),
    path('pagamentos/portal/', views_payments.stripe_portal, name='stripe_portal'),
    path('pagamentos/webhook/', views_payments.stripe_webhook, name='stripe_webhook'),
]
