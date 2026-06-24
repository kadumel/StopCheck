from django.urls import path

from . import views
from . import views_driver
from . import views_import
from . import views_payments

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('offline/', views.offline_view, name='offline'),
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('registar/', views.register_view, name='register'),
    path('registar/verificar/', views.verify_email_view, name='verify_email'),
    path('registar/reenviar/', views.resend_verification_view, name='resend_verification'),

    path('comparacoes/', views.comparison_list, name='comparison_list'),
    path('comparacoes/digitacao/', views.comparison_bulk_entry, name='comparison_bulk_entry'),
    path('comparacoes/nova/', views.comparison_create, name='comparison_create'),
    path('comparacoes/<int:pk>/editar/', views.comparison_edit, name='comparison_edit'),
    path('comparacoes/<int:pk>/limpar/', views.comparison_clear, name='comparison_clear'),
    path('comparacoes/<int:pk>/libertar-motorista/', views.comparison_unlock_driver, name='comparison_unlock_driver'),
    path('comparacoes/<int:pk>/bloquear-motorista/', views.comparison_lock_driver, name='comparison_lock_driver'),
    path('comparacoes/<int:pk>/sincronizar-financeiro/', views.comparison_sync_finance, name='comparison_sync_finance'),
    path('comparacoes/<int:pk>/eliminar/', views.comparison_delete, name='comparison_delete'),

    path('frota/', views.vehicle_list, name='vehicle_list'),
    path('frota/nova/', views.vehicle_create, name='vehicle_create'),
    path('frota/<int:pk>/editar/', views.vehicle_edit, name='vehicle_edit'),
    path('frota/<int:pk>/eliminar/', views.vehicle_delete, name='vehicle_delete'),

    path('motoristas/', views.driver_list, name='driver_list'),
    path('motoristas/novo/', views.driver_create, name='driver_create'),
    path('motoristas/<int:pk>/editar/', views.driver_edit, name='driver_edit'),
    path('motoristas/<int:pk>/eliminar/', views.driver_delete, name='driver_delete'),

    path('rotas/', views.route_list, name='route_list'),
    path('rotas/empresas/nova/', views.delivery_company_create, name='delivery_company_create'),
    path('rotas/empresas/<int:pk>/editar/', views.delivery_company_edit, name='delivery_company_edit'),
    path('rotas/empresas/<int:pk>/eliminar/', views.delivery_company_delete, name='delivery_company_delete'),
    path('rotas/catalogo/nova/', views.company_route_create, name='company_route_create'),
    path('rotas/catalogo/<int:pk>/editar/', views.company_route_edit, name='company_route_edit'),
    path('rotas/catalogo/<int:pk>/eliminar/', views.company_route_delete, name='company_route_delete'),
    path('producao/', views.production_list, name='production_list'),
    path('producao/nova/', views.route_create, name='route_create'),
    path('producao/<int:pk>/editar/', views.route_edit, name='route_edit'),
    path('producao/<int:pk>/eliminar/', views.route_delete, name='route_delete'),
    path('producao/eliminar/', views.route_bulk_delete, name='route_bulk_delete'),

    path('combustivel/', views.fuel_list, name='fuel_list'),
    path('combustivel/novo/', views.fuel_create, name='fuel_create'),
    path('combustivel/<int:pk>/editar/', views.fuel_edit, name='fuel_edit'),
    path('combustivel/<int:pk>/eliminar/', views.fuel_delete, name='fuel_delete'),

    path('despesas/', views.expense_list, name='expense_list'),
    path('despesas/nova/', views.expense_create, name='expense_create'),
    path('despesas/<int:pk>/editar/', views.expense_edit, name='expense_edit'),
    path('despesas/<int:pk>/eliminar/', views.expense_delete, name='expense_delete'),
    path('despesas/eliminar/', views.expense_bulk_delete, name='expense_bulk_delete'),
    path('registos/plano-contas/', views.financial_account_list, name='financial_account_list'),
    path('registos/plano-contas/novo/', views.financial_account_create, name='financial_account_create'),
    path('registos/plano-contas/<int:pk>/editar/', views.financial_account_edit, name='financial_account_edit'),
    path('registos/plano-contas/<int:pk>/eliminar/', views.financial_account_delete, name='financial_account_delete'),
    path('financeiro/receitas/', views.revenue_list, name='revenue_list'),
    path('financeiro/receitas/nova/', views.revenue_create, name='revenue_create'),
    path('financeiro/receitas/<int:pk>/editar/', views.revenue_edit, name='revenue_edit'),
    path('financeiro/receitas/<int:pk>/eliminar/', views.revenue_delete, name='revenue_delete'),
    path('financeiro/receitas/eliminar/', views.revenue_bulk_delete, name='revenue_bulk_delete'),
    path('financeiro/', views.finance_view, name='finance'),
    path('assinatura/', views.subscription_view, name='subscription'),

    path('exportar/excel/', views.export_excel, name='export_excel'),
    path('exportar/pdf/', views.export_pdf, name='export_pdf'),

    # App mobile motorista
    path('sw.js', views_driver.service_worker, name='service_worker'),
    path('serviceworker.js', views_driver.service_worker, name='service_worker_legacy'),
    path('motorista/csrf/', views_driver.driver_csrf, name='driver_csrf'),
    path('motorista/', views_driver.driver_app, name='driver_app'),
    path('motorista/registar/', views_driver.driver_log_event, name='driver_log_event'),
    path('motorista/concluir/', views_driver.driver_submit_data, name='driver_submit_data'),
    path('motorista/historico/', views_driver.driver_history, name='driver_history'),

    # Importação ficheiros empresa
    path('importar/', views_import.import_list, name='import_list'),
    path('importar/novo/', views_import.import_upload, name='import_upload'),
    path('importar/<int:pk>/', views_import.import_detail, name='import_detail'),
    path('empresas-entrega/', views.route_list, name='delivery_company_list'),

    # Pagamentos Stripe
    path('pagamentos/checkout/', views_payments.stripe_checkout, name='stripe_checkout'),
    path('pagamentos/portal/', views_payments.stripe_portal, name='stripe_portal'),
    path('pagamentos/webhook/', views_payments.stripe_webhook, name='stripe_webhook'),
]
