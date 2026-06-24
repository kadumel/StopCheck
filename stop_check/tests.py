from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from stop_check.models import (
    CompanyRoute,
    DeliveryCompany,
    Organization,
    Subscription,
    SubscriptionInvoice,
    SubscriptionTariff,
)
from stop_check.services.billing_service import (
    at_route_limit,
    build_subscription_period_context,
    calculate_route_addition_prorata,
    can_request_additional_routes,
    create_initial_prorata_invoice,
    create_monthly_invoice,
    create_route_addition_request,
    due_date_for_period,
    get_catalog_route_limit,
    mark_invoice_paid,
    resolve_contract_date,
)


class SubscriptionPricingTests(TestCase):
    def setUp(self):
        self.tariff, _ = SubscriptionTariff.objects.update_or_create(
            pk=1,
            defaults={
                'included_routes': 5,
                'price_first_route': Decimal('20.00'),
                'price_additional_route': Decimal('5.00'),
                'trial_days': 31,
            },
        )

    def _register_routes(self, org, count):
        company = DeliveryCompany.objects.create(
            organization=org, name='GLS',
        )
        for i in range(count):
            CompanyRoute.objects.create(
                organization=org,
                delivery_company=company,
                name=f'R{i + 1}',
            )

    def test_base_price_up_to_five_routes(self):
        self.assertEqual(Subscription.calculate_price(1), Decimal('20.00'))
        self.assertEqual(Subscription.calculate_price(5), Decimal('20.00'))

    def test_additional_routes(self):
        self.assertEqual(Subscription.calculate_price(6), Decimal('25.00'))
        self.assertEqual(Subscription.calculate_price(7), Decimal('30.00'))

    def test_prorata_july_ten_to_end(self):
        from datetime import date
        amount = Subscription.calculate_prorata(
            Decimal('20.00'), date(2026, 7, 10), date(2026, 7, 31),
        )
        self.assertEqual(amount, Decimal('14.19'))
        details = Subscription.calculate_prorata_details(
            Decimal('20.00'), date(2026, 7, 10), date(2026, 7, 31),
        )
        self.assertEqual(details['days_in_month'], 31)
        self.assertEqual(details['billable_days'], 22)

    def test_initial_invoice_prorata_at_trial_end(self):
        from datetime import date
        org = Organization.objects.create(name='TrialInv', email='ti@test.com')
        sub = Subscription.objects.create(
            organization=org,
            status=Subscription.STATUS_TRIAL,
            start_date=date(2026, 6, 10),
            trial_end_date=date(2026, 7, 10),
        )
        invoice, _ = create_initial_prorata_invoice(sub, 2, date(2026, 6, 20))
        self.assertEqual(invoice.period_start, date(2026, 6, 20))
        self.assertEqual(invoice.period_end, date(2026, 6, 30))
        self.assertEqual(invoice.amount, Decimal('7.33'))

    def test_prorata_half_month(self):
        from datetime import date
        amount = Subscription.calculate_prorata(
            Decimal('20.00'), date(2026, 6, 15), date(2026, 6, 30),
        )
        self.assertEqual(amount, Decimal('10.67'))

    def test_route_addition_prorata_formula(self):
        from datetime import date
        amount = calculate_route_addition_prorata(1, request_date=date(2026, 6, 15))
        self.assertEqual(amount, Decimal('2.67'))

    def test_trial_end_inclusive(self):
        from datetime import date
        end = Subscription.calculate_trial_end_date(date(2026, 6, 10), 31)
        self.assertEqual(end, date(2026, 7, 10))

    def test_trial_period_context(self):
        from datetime import date
        org = Organization.objects.create(name='Trial', email='trial@test.com')
        sub = Subscription.objects.create(
            organization=org,
            status=Subscription.STATUS_TRIAL,
            start_date=date(2026, 6, 10),
            trial_end_date=date(2026, 7, 10),
        )
        ctx = build_subscription_period_context(sub, date(2026, 6, 15))
        self.assertTrue(ctx['is_trial'])
        self.assertEqual(ctx['trial_end'], date(2026, 7, 10))
        self.assertEqual(ctx['period_lines'], [])
        self.assertIsNone(ctx['subscription_start'])

    def test_period_before_subscription_starts(self):
        from datetime import date
        org = Organization.objects.create(name='Future', email='f@test.com')
        sub = Subscription.objects.create(
            organization=org,
            status=Subscription.STATUS_ACTIVE,
            start_date=date(2026, 6, 10),
            trial_end_date=date(2026, 7, 10),
            contracted_routes=2,
        )
        ctx = build_subscription_period_context(sub, date(2026, 6, 24))
        self.assertTrue(ctx['billing_starts_in_future'])
        self.assertEqual(ctx['subscription_start'], date(2026, 7, 10))
        self.assertEqual(ctx['subscription_end'], date(2026, 7, 31))
        self.assertEqual(len(ctx['period_lines']), 1)
        self.assertEqual(ctx['period_lines'][0]['start'], date(2026, 7, 10))
        self.assertEqual(ctx['period_lines'][0]['end'], date(2026, 7, 31))
        self.assertTrue(ctx['period_lines'][0]['is_prorata'])
        self.assertEqual(ctx['period_lines'][0]['amount'], Decimal('14.19'))
        self.assertEqual(ctx['period_lines'][0]['billable_days'], 22)

    def test_contract_during_trial_uses_contract_date(self):
        from datetime import date
        org = Organization.objects.create(name='TrialC', email='tc@test.com')
        sub = Subscription.objects.create(
            organization=org,
            status=Subscription.STATUS_TRIAL,
            start_date=date(2026, 6, 10),
            trial_end_date=date(2026, 7, 10),
        )
        resolved = resolve_contract_date(sub, date(2026, 6, 20))
        self.assertEqual(resolved, date(2026, 6, 20))
        invoice, _ = create_initial_prorata_invoice(sub, 2, date(2026, 6, 20))
        self.assertEqual(invoice.period_start, date(2026, 6, 20))
        self.assertEqual(invoice.period_end, date(2026, 6, 30))

    def test_initial_invoice_on_contract(self):
        org = Organization.objects.create(name='Test', email='t@test.com')
        sub = Subscription.objects.create(organization=org, status=Subscription.STATUS_PENDING)
        invoice, created = create_initial_prorata_invoice(
            sub, 5, contract_date=timezone.localdate().replace(day=15),
        )
        self.assertTrue(created)
        self.assertEqual(invoice.invoice_type, SubscriptionInvoice.TYPE_PRORATA_INITIAL)
        self.assertEqual(invoice.route_count, 5)

    def test_monthly_invoice_due_on_fifth(self):
        from datetime import date
        org = Organization.objects.create(name='Test2', email='t2@test.com')
        sub = Subscription.objects.create(
            organization=org,
            status=Subscription.STATUS_ACTIVE,
            contracted_routes=5,
        )
        period = date(2026, 7, 1)
        invoice, _ = create_monthly_invoice(sub, period)
        self.assertEqual(invoice.due_date, due_date_for_period(period))
        self.assertEqual(invoice.due_date.day, 5)

    def test_route_addition_requires_base_routes(self):
        from datetime import date
        org = Organization.objects.create(name='Test5', email='t5@test.com')
        sub = Subscription.objects.create(
            organization=org,
            status=Subscription.STATUS_ACTIVE,
            contracted_routes=5,
        )
        with self.assertRaises(ValueError):
            create_route_addition_request(sub, 1, request_date=date(2026, 6, 15))

    def test_route_addition_request(self):
        from datetime import date
        org = Organization.objects.create(name='Test4', email='t4@test.com')
        sub = Subscription.objects.create(
            organization=org,
            status=Subscription.STATUS_ACTIVE,
            contracted_routes=5,
        )
        self._register_routes(org, 5)
        route_request = create_route_addition_request(
            sub, 2, request_date=date(2026, 6, 15),
        )
        self.assertEqual(route_request.additional_routes, 2)
        self.assertEqual(route_request.invoice.route_count, 2)
        mark_invoice_paid(route_request.invoice)
        sub.refresh_from_db()
        self.assertEqual(sub.contracted_routes, 7)
        route_request.refresh_from_db()
        self.assertEqual(route_request.status, 'paid')

    def test_trial_route_limit_five(self):
        from datetime import date
        org = Organization.objects.create(name='TrialLimit', email='tl@test.com')
        sub = Subscription.objects.create(
            organization=org,
            status=Subscription.STATUS_TRIAL,
            start_date=date(2026, 6, 10),
            trial_end_date=date(2026, 7, 10),
        )
        self.assertEqual(get_catalog_route_limit(sub), 5)
        self.assertFalse(at_route_limit(sub, org))
        self._register_routes(org, 5)
        self.assertTrue(at_route_limit(sub, org))
        self.assertFalse(can_request_additional_routes(sub, org))
        self.assertEqual(sub.available_route_slots, 0)

    def test_pending_limited_until_payment(self):
        from datetime import date
        org = Organization.objects.create(name='PendingLimit', email='pl@test.com')
        sub = Subscription.objects.create(
            organization=org,
            status=Subscription.STATUS_PENDING,
            contracted_routes=8,
        )
        self.assertEqual(get_catalog_route_limit(sub), 5)
        self._register_routes(org, 5)
        self.assertTrue(at_route_limit(sub, org))

    def test_active_route_limit_uses_contracted(self):
        org = Organization.objects.create(name='ActiveLimit', email='al@test.com')
        sub = Subscription.objects.create(
            organization=org,
            status=Subscription.STATUS_ACTIVE,
            contracted_routes=7,
        )
        self._register_routes(org, 6)
        self.assertFalse(at_route_limit(sub, org))
        self._register_routes(org, 1)
        self.assertTrue(at_route_limit(sub, org))

    def test_mark_invoice_paid_activates_subscription(self):
        org = Organization.objects.create(name='Test3', email='t3@test.com')
        sub = Subscription.objects.create(
            organization=org,
            status=Subscription.STATUS_PENDING,
        )
        invoice, _ = create_initial_prorata_invoice(sub, 5)
        mark_invoice_paid(invoice)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(sub.contracted_routes, 5)

    def test_paid_prorata_shows_next_month_billing_period(self):
        from datetime import date
        org = Organization.objects.create(name='PaidProrata', email='pp@test.com')
        sub = Subscription.objects.create(
            organization=org,
            status=Subscription.STATUS_PENDING,
            contracted_routes=5,
            start_date=date(2026, 6, 10),
            trial_end_date=date(2026, 7, 23),
        )
        invoice, _ = create_initial_prorata_invoice(sub, 5, date(2026, 6, 24))
        self.assertEqual(invoice.period_start, date(2026, 6, 24))
        self.assertEqual(invoice.period_end, date(2026, 6, 30))
        mark_invoice_paid(invoice, paid_date=date(2026, 6, 24))
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)
        ctx = build_subscription_period_context(sub, date(2026, 6, 24))
        self.assertEqual(ctx['period_lines'][0]['start'], date(2026, 6, 24))
        self.assertEqual(ctx['period_lines'][0]['end'], date(2026, 6, 30))
        self.assertEqual(ctx['period_lines'][0]['status'], SubscriptionInvoice.STATUS_PAID)
        self.assertIsNotNone(ctx['next_billing_period'])
        self.assertEqual(ctx['next_billing_period']['start'], date(2026, 7, 1))
        self.assertEqual(ctx['next_billing_period']['end'], date(2026, 7, 31))

    def test_invoice_save_as_paid_activates_subscription(self):
        org = Organization.objects.create(name='AdminPaid', email='ap@test.com')
        sub = Subscription.objects.create(
            organization=org,
            status=Subscription.STATUS_PENDING,
            contracted_routes=5,
        )
        invoice, _ = create_initial_prorata_invoice(sub, 5)
        invoice.status = SubscriptionInvoice.STATUS_PAID
        invoice.paid_at = timezone.localdate()
        invoice.save()
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(sub.contracted_routes, 5)

    def test_sync_subscription_payment_state_repairs_pending(self):
        from datetime import date
        from stop_check.services.billing_service import sync_subscription_payment_state

        org = Organization.objects.create(name='Repair', email='r@test.com')
        sub = Subscription.objects.create(
            organization=org,
            status=Subscription.STATUS_PENDING,
            contracted_routes=7,
        )
        invoice, _ = create_initial_prorata_invoice(sub, 7, date(2026, 7, 24))
        SubscriptionInvoice.objects.filter(pk=invoice.pk).update(
            status=SubscriptionInvoice.STATUS_PAID,
        )
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_PENDING)
        sync_subscription_payment_state(sub)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(sub.contracted_routes, 7)
        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.paid_at)

    def test_period_context_single_full_month(self):
        from datetime import date
        org = Organization.objects.create(name='Test6', email='t6@test.com')
        sub = Subscription.objects.create(
            organization=org,
            status=Subscription.STATUS_ACTIVE,
            start_date=date(2026, 1, 1),
            contracted_routes=5,
        )
        create_monthly_invoice(sub, date(2026, 7, 1))
        ctx = build_subscription_period_context(sub, date(2026, 7, 15))
        self.assertTrue(ctx['single_period'])
        self.assertEqual(len(ctx['period_lines']), 1)
        self.assertEqual(ctx['period_lines'][0]['start'], date(2026, 7, 1))
        self.assertEqual(ctx['period_lines'][0]['end'], date(2026, 7, 31))

    def test_period_context_with_prorata_routes(self):
        from datetime import date
        org = Organization.objects.create(name='Test7', email='t7@test.com')
        sub = Subscription.objects.create(
            organization=org,
            status=Subscription.STATUS_ACTIVE,
            start_date=date(2026, 1, 1),
            contracted_routes=5,
        )
        self._register_routes(org, 5)
        create_monthly_invoice(sub, date(2026, 6, 1))
        create_route_addition_request(sub, 2, request_date=date(2026, 6, 15))
        ctx = build_subscription_period_context(sub, date(2026, 6, 20))
        self.assertFalse(ctx['single_period'])
        self.assertEqual(len(ctx['period_lines']), 2)
        self.assertFalse(ctx['period_lines'][0]['is_prorata'])
        self.assertTrue(ctx['period_lines'][1]['is_prorata'])


class RevenueSyncTests(TestCase):
    def test_no_revenue_until_productivity_launched(self):
        from datetime import date

        from stop_check.models import Driver, FinancialAccount, Route, Vehicle
        from stop_check.services.production_service import ensure_comparison_for_route

        org = Organization.objects.create(name='RevOrg', email='rev@test.com')
        account = FinancialAccount.objects.create(
            organization=org, name='Entregas', color='#059669',
            account_type=FinancialAccount.TYPE_REVENUE,
        )
        company = DeliveryCompany.objects.create(organization=org, name='GLS')
        company_route = CompanyRoute.objects.create(
            organization=org,
            delivery_company=company,
            name='LIS-01',
            daily_rate=Decimal('25.00'),
            revenue_account=account,
            daily_rate_account=account,
        )
        driver = Driver.objects.create(
            organization=org, name='João Motorista', nif='123456789',
        )
        vehicle = Vehicle.objects.create(
            organization=org, plate='AB-12-CD', brand='Ford', model='Transit',
        )
        route = Route.objects.create(
            organization=org,
            company_route=company_route,
            name=company_route.name,
            date=date(2026, 6, 24),
            driver=driver,
            vehicle=vehicle,
            delivery_company=company,
        )
        comparison = ensure_comparison_for_route(route)

        self.assertFalse(comparison.revenue_entries.exists())

        comparison.driver_stops = 1
        comparison.save()
        comparison.refresh_from_db()

        daily_revenue = comparison.revenue_entries.filter(
            revenue_kind='daily_rate',
        ).first()
        self.assertIsNotNone(daily_revenue)
        self.assertEqual(daily_revenue.amount, Decimal('25.00'))
        self.assertEqual(comparison.snapshot_daily_rate, Decimal('25.00'))

    def test_daily_rate_zero_at_launch_not_added_after_route_change(self):
        from datetime import date

        from stop_check.models import Driver, FinancialAccount, Route, Vehicle
        from stop_check.services.production_service import ensure_comparison_for_route
        from stop_check.services.revenue_service import sync_revenue_for_comparison

        org = Organization.objects.create(name='RevOrg5', email='rev5@test.com')
        account = FinancialAccount.objects.create(
            organization=org, name='Diárias', color='#2563eb',
            account_type=FinancialAccount.TYPE_REVENUE,
        )
        company = DeliveryCompany.objects.create(organization=org, name='GLS')
        company_route = CompanyRoute.objects.create(
            organization=org,
            delivery_company=company,
            name='LIS-05',
            daily_rate=Decimal('0.00'),
            price_per_stop=Decimal('2.00'),
            revenue_account=account,
            daily_rate_account=account,
        )
        driver = Driver.objects.create(
            organization=org, name='Sara Motorista', nif='777888999',
        )
        vehicle = Vehicle.objects.create(
            organization=org, plate='CC-55-DD', brand='Ford', model='Transit',
        )
        route = Route.objects.create(
            organization=org,
            company_route=company_route,
            name=company_route.name,
            date=date(2026, 6, 28),
            driver=driver,
            vehicle=vehicle,
            delivery_company=company,
        )
        comparison = ensure_comparison_for_route(route)
        comparison.driver_stops = 2
        comparison.save()

        self.assertFalse(
            comparison.revenue_entries.filter(revenue_kind='daily_rate').exists()
        )
        self.assertEqual(comparison.snapshot_daily_rate, Decimal('0.00'))

        company_route.daily_rate = Decimal('40.00')
        company_route.save()
        comparison.refresh_from_db()
        sync_revenue_for_comparison(comparison)

        self.assertFalse(
            comparison.revenue_entries.filter(revenue_kind='daily_rate').exists()
        )

    def test_productivity_and_daily_rate_create_separate_revenues(self):
        from datetime import date

        from stop_check.models import Driver, FinancialAccount, Route, Vehicle
        from stop_check.services.production_service import ensure_comparison_for_route

        org = Organization.objects.create(name='RevOrg2', email='rev2@test.com')
        prod_account = FinancialAccount.objects.create(
            organization=org, name='Entregas', color='#059669',
            account_type=FinancialAccount.TYPE_REVENUE,
        )
        daily_account = FinancialAccount.objects.create(
            organization=org, name='Diárias', color='#2563eb',
            account_type=FinancialAccount.TYPE_REVENUE,
        )
        company = DeliveryCompany.objects.create(organization=org, name='GLS')
        company_route = CompanyRoute.objects.create(
            organization=org,
            delivery_company=company,
            name='LIS-02',
            daily_rate=Decimal('30.00'),
            price_per_stop=Decimal('2.00'),
            revenue_account=prod_account,
            daily_rate_account=daily_account,
        )
        driver = Driver.objects.create(
            organization=org, name='Ana Motorista', nif='987654321',
        )
        vehicle = Vehicle.objects.create(
            organization=org, plate='XY-99-ZZ', brand='Ford', model='Transit',
        )
        route = Route.objects.create(
            organization=org,
            company_route=company_route,
            name=company_route.name,
            date=date(2026, 6, 25),
            driver=driver,
            vehicle=vehicle,
            delivery_company=company,
        )
        comparison = ensure_comparison_for_route(route)
        comparison.driver_stops = 5
        comparison.save()

        entries = {
            r.revenue_kind: r for r in comparison.revenue_entries.all()
        }
        self.assertEqual(entries['productivity'].amount, Decimal('10.00'))
        self.assertEqual(entries['productivity'].account_id, prod_account.pk)
        self.assertEqual(entries['daily_rate'].amount, Decimal('30.00'))
        self.assertEqual(entries['daily_rate'].account_id, daily_account.pk)

    def test_zero_daily_rate_does_not_create_daily_revenue(self):
        from datetime import date

        from stop_check.models import Driver, FinancialAccount, Route, Vehicle
        from stop_check.services.production_service import ensure_comparison_for_route

        org = Organization.objects.create(name='RevOrg3', email='rev3@test.com')
        prod_account = FinancialAccount.objects.create(
            organization=org, name='Entregas', color='#059669',
            account_type=FinancialAccount.TYPE_REVENUE,
        )
        daily_account = FinancialAccount.objects.create(
            organization=org, name='Diárias', color='#2563eb',
            account_type=FinancialAccount.TYPE_REVENUE,
        )
        company = DeliveryCompany.objects.create(organization=org, name='GLS')
        company_route = CompanyRoute.objects.create(
            organization=org,
            delivery_company=company,
            name='LIS-03',
            daily_rate=Decimal('0.00'),
            price_per_stop=Decimal('2.00'),
            revenue_account=prod_account,
            daily_rate_account=daily_account,
        )
        driver = Driver.objects.create(
            organization=org, name='Pedro Motorista', nif='111222333',
        )
        vehicle = Vehicle.objects.create(
            organization=org, plate='ZZ-11-YY', brand='Ford', model='Transit',
        )
        route = Route.objects.create(
            organization=org,
            company_route=company_route,
            name=company_route.name,
            date=date(2026, 6, 26),
            driver=driver,
            vehicle=vehicle,
            delivery_company=company,
        )
        comparison = ensure_comparison_for_route(route)
        comparison.driver_stops = 3
        comparison.save()

        self.assertFalse(
            comparison.revenue_entries.filter(revenue_kind='daily_rate').exists()
        )
        productivity = comparison.revenue_entries.filter(
            revenue_kind='productivity',
        ).first()
        self.assertIsNotNone(productivity)
        self.assertEqual(productivity.amount, Decimal('6.00'))

    def test_route_daily_rate_change_preserves_historical_revenue(self):
        from datetime import date

        from stop_check.models import Driver, FinancialAccount, Route, Vehicle
        from stop_check.services.production_service import ensure_comparison_for_route
        from stop_check.services.revenue_service import sync_revenue_for_comparison

        org = Organization.objects.create(name='RevOrg4', email='rev4@test.com')
        account = FinancialAccount.objects.create(
            organization=org, name='Diárias', color='#2563eb',
            account_type=FinancialAccount.TYPE_REVENUE,
        )
        company = DeliveryCompany.objects.create(organization=org, name='GLS')
        company_route = CompanyRoute.objects.create(
            organization=org,
            delivery_company=company,
            name='LIS-04',
            daily_rate=Decimal('25.00'),
            price_per_stop=Decimal('2.00'),
            revenue_account=account,
            daily_rate_account=account,
        )
        driver = Driver.objects.create(
            organization=org, name='Rui Motorista', nif='444555666',
        )
        vehicle = Vehicle.objects.create(
            organization=org, plate='AA-44-BB', brand='Ford', model='Transit',
        )
        route = Route.objects.create(
            organization=org,
            company_route=company_route,
            name=company_route.name,
            date=date(2026, 6, 27),
            driver=driver,
            vehicle=vehicle,
            delivery_company=company,
        )
        comparison = ensure_comparison_for_route(route)
        comparison.driver_stops = 5
        comparison.save()

        daily_revenue = comparison.revenue_entries.get(revenue_kind='daily_rate')
        self.assertEqual(daily_revenue.amount, Decimal('25.00'))

        company_route.daily_rate = Decimal('40.00')
        company_route.save()

        comparison.refresh_from_db()
        sync_revenue_for_comparison(comparison)
        daily_revenue.refresh_from_db()
        comparison.refresh_from_db()

        self.assertEqual(daily_revenue.amount, Decimal('25.00'))
        self.assertEqual(comparison.snapshot_daily_rate, Decimal('25.00'))
