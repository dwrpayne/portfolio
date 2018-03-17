"""
This file demonstrates writing tests using the unittest module. These will pass
when you run "manage.py test".

Replace this with more appropriate tests for your application.
"""

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from .urls import urlpatterns

from datetime import date, timedelta
from decimal import Decimal
from .models import HoldingDetail, BaseAccount
from securities.models import Security, SecurityPriceDetail

from .templatetags import mytags


def setUpModule():
    security1 = Security.stocks.create(symbol='TSLA', currency='USD')
    security2 = Security.stocks.create(symbol='MSFT', currency='USD')
    usd = Security.cash.create(symbol='USD')

    security1.prices.create(day=date.today(), price=300)
    security1.prices.create(day=date.today() - timedelta(days=1), price=310)
    security2.prices.create(day=date.today(), price=55)
    security2.prices.create(day=date.today() - timedelta(days=1), price=50)
    usd.prices.create(day=date.today(), price=1.2)
    usd.prices.create(day=date.today() - timedelta(days=1), price=1.15)

    SecurityPriceDetail.CreateView()
    SecurityPriceDetail.Refresh()


class HoldingChangeTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.account1 = BaseAccount.objects.create(type='Test', account_id='123')
        cls.account2 = BaseAccount.objects.create(type='Test', account_id='456')
        cls.security1 = Security.stocks.get(symbol='TSLA')
        cls.security2 = Security.stocks.get(symbol='MSFT')

    def test_change_days_basic(self):
        today = HoldingDetail(account=self.account1, security=self.security1, day=date.today(),
                              qty=50, price=300, exch=1.2, cad=360, value=18000, type='Stock')
        yesterday = HoldingDetail(account=self.account1, security=self.security1,
                                      day=date.today() - timedelta(days=1),
                                      qty=50, price=310, exch=1.15, cad=356.5, value=18600, type='Stock')
        change = today - yesterday
        self.assertEqual(change.qty, today.qty)
        self.assertEqual(change.qty_delta, today.qty-yesterday.qty)
        self.assertEqual(change.value, today.value)
        self.assertEqual(change.value_delta, today.value-yesterday.value)
        self.assertEqual(change.price, today.price)
        self.assertEqual(change.price_delta, today.price-yesterday.price)


    def test_change_days_purchase(self):
        today = HoldingDetail(account=self.account1, security=self.security1, day=date.today(),
                              qty=50, price=300, exch=1.2, cad=360, value=18000, type='Stock')
        yesterday = HoldingDetail(account=self.account1, security=self.security1,
                                      day=date.today() - timedelta(days=1),
                                      qty=100, price=310, exch=1.15, cad=356.5, value=35650, type='Stock')
        change = today - yesterday
        self.assertEqual(change.qty, today.qty)
        self.assertEqual(change.qty_delta, today.qty-yesterday.qty)
        self.assertEqual(change.value, today.value)
        self.assertEqual(change.value_delta, today.value-yesterday.value)
        self.assertEqual(change.price, today.price)
        self.assertEqual(change.price_delta, today.price-yesterday.price)

    def test_change_days_purchase_new(self):
        today = HoldingDetail(account=self.account1, security=self.security1, day=date.today(),
                              qty=50, price=300, exch=1.2, cad=360, value=18000, type='Stock')
        change = today - 0
        self.assertEqual(change.qty, today.qty)
        self.assertEqual(change.qty_delta, today.qty)
        self.assertEqual(change.value, today.value)
        self.assertEqual(change.value_delta, today.value)
        self.assertEqual(change.price, today.price)
        self.assertEqual(change.price_delta, today.price-today.security.pricedetails.get(day=date.today()-timedelta(days=1)).price)

    def test_change_days_sell(self):
        today = HoldingDetail(account=self.account1, security=self.security1, day=date.today(),
                              qty=50, price=300, exch=1.2, cad=360, value=18000, type='Stock')
        yesterday = HoldingDetail(account=self.account1, security=self.security1,
                                      day=date.today() - timedelta(days=1),
                                      qty=20, price=310, exch=1.15, cad=356.5, value=7130, type='Stock')
        change = today - yesterday
        self.assertEqual(change.qty, today.qty)
        self.assertEqual(change.qty_delta, today.qty-yesterday.qty)
        self.assertEqual(change.value, today.value)
        self.assertEqual(change.value_delta, today.value-yesterday.value)
        self.assertEqual(change.price, today.price)
        self.assertEqual(change.price_delta, today.price-yesterday.price)

    def test_change_days_sell_all(self):
        yesterday = HoldingDetail(account=self.account1, security=self.security1, day=date.today() - timedelta(days=1),
                              qty=50, price=310, exch=1.15, cad=356.5, value=178250, type='Stock')

        change = 0 - yesterday
        self.assertEqual(change.qty, 0)
        self.assertEqual(change.qty_delta, -yesterday.qty)
        self.assertEqual(change.value, 0)
        self.assertEqual(change.value_delta, -yesterday.value)
        self.assertEqual(change.price, yesterday.security.pricedetails.get(day=date.today()).price)
        self.assertEqual(change.price_delta, yesterday.security.pricedetails.get(day=date.today()).price-yesterday.price)

    def test_add_changes_same_security(self):
        today = HoldingDetail(account=self.account1, security=self.security1, day=date.today(),
                              qty=50, price=300, exch=1.2, cad=360, value=18000, type='Stock')
        yesterday = HoldingDetail(account=self.account1, security=self.security1,
                                      day=date.today() - timedelta(days=1),
                                      qty=50, price=310, exch=1.15, cad=356.5, value=178250, type='Stock')
        today2 = HoldingDetail(account=self.account2, security=self.security1, day=date.today(),
                              qty=500, price=300, exch=1.2, cad=360, value=180000, type='Stock')
        yesterday2 = HoldingDetail(account=self.account2, security=self.security1,
                                      day=date.today() - timedelta(days=1),
                                      qty=500, price=310, exch=1.15, cad=356.5, value=1782500, type='Stock')
        change = today - yesterday
        change2 = today2 - yesterday2
        total_change = sum((change, change2))

        self.assertEqual(total_change.qty, change.qty+change2.qty)
        self.assertEqual(total_change.qty_delta, change.qty_delta+change2.qty_delta)
        self.assertEqual(total_change.value, change.value+change2.value)
        self.assertEqual(total_change.value_delta, change.value_delta+change2.value_delta)
        self.assertEqual(total_change.price, change.price)
        self.assertEqual(change.price, change2.price)
        self.assertEqual(total_change.price_delta, change.price_delta)
        self.assertEqual(change.price_delta, change2.price_delta)

    def test_add_changes_same_account(self):
        today = HoldingDetail(account=self.account1, security=self.security1, day=date.today(),
                              qty=50, price=300, exch=1.2, cad=360, value=18000, type='Stock')
        yesterday = HoldingDetail(account=self.account1, security=self.security1,
                                      day=date.today() - timedelta(days=1),
                                      qty=50, price=310, exch=1.15, cad=356.5, value=17825, type='Stock')
        today2 = HoldingDetail(account=self.account2, security=self.security2, day=date.today(),
                              qty=100, price=55, exch=1.2, cad=66, value=6600, type='Stock')
        yesterday2 = HoldingDetail(account=self.account2, security=self.security2,
                                      day=date.today() - timedelta(days=1),
                                      qty=100, price=50, exch=1.15, cad=57.5, value=5750, type='Stock')
        change = today - yesterday
        change2 = today2 - yesterday2
        total_change = sum((change, change2))

        self.assertEqual(total_change.value, change.value+change2.value)
        self.assertEqual(total_change.value_delta, change.value_delta+change2.value_delta)

    def test_add_changes_whole_portfolio(self):
        today = HoldingDetail(account=self.account1, security=self.security1, day=date.today(),
                              qty=50, price=300, exch=1.2, cad=360, value=18000, type='Stock')
        yesterday = HoldingDetail(account=self.account1, security=self.security1,
                                      day=date.today() - timedelta(days=1),
                                      qty=50, price=310, exch=1.15, cad=356.5, value=17825, type='Stock')
        today2 = HoldingDetail(account=self.account1, security=self.security2, day=date.today(),
                              qty=500, price=300, exch=1.2, cad=360, value=180000, type='Stock')
        yesterday2 = HoldingDetail(account=self.account1, security=self.security2,
                                      day=date.today() - timedelta(days=1),
                                      qty=500, price=310, exch=1.15, cad=356.5, value=178250, type='Stock')
        today3 = HoldingDetail(account=self.account2, security=self.security2, day=date.today(),
                              qty=100, price=55, exch=1.2, cad=66, value=6600, type='Stock')
        yesterday3 = HoldingDetail(account=self.account2, security=self.security2,
                                      day=date.today() - timedelta(days=1),
                                      qty=100, price=50, exch=1.15, cad=57.5, value=5750, type='Stock')
        change = today - yesterday
        change2 = today2 - yesterday2
        change3 = today3 - yesterday3
        total_change = sum((change, change2, change3))

        self.assertEqual(total_change.value, change.value+change2.value+change3.value)
        self.assertEqual(total_change.value_delta, change.value_delta+change2.value_delta+change3.value_delta)

    def test_add_changes_whole_portfolio_buy_sell(self):
        today = HoldingDetail(account=self.account1, security=self.security1, day=date.today(),
                              qty=50, price=300, exch=1.2, cad=360, value=18000, type='Stock')
        yesterday = HoldingDetail(account=self.account1, security=self.security1,
                                      day=date.today() - timedelta(days=1),
                                      qty=100, price=310, exch=1.15, cad=356.5, value=35650, type='Stock')
        today2 = HoldingDetail(account=self.account1, security=self.security2, day=date.today(),
                              qty=500, price=300, exch=1.2, cad=360, value=180000, type='Stock')
        yesterday2 = HoldingDetail(account=self.account1, security=self.security2,
                                      day=date.today() - timedelta(days=1),
                                      qty=100, price=310, exch=1.15, cad=356.5, value=35650, type='Stock')
        today3 = HoldingDetail(account=self.account2, security=self.security2, day=date.today(),
                              qty=100, price=55, exch=1.2, cad=66, value=6600, type='Stock')

        change = today - yesterday
        change2 = today2 - yesterday2
        change3 = today3 - 0
        total_change = sum((change, change2, change3))

        self.assertEqual(total_change.value, change.value+change2.value+change3.value)
        self.assertEqual(total_change.value_delta, change.value_delta+change2.value_delta+change3.value_delta)

    def test_add_changes_whole_portfolio_buy_sell_2(self):
        yesterday = HoldingDetail(account=self.account1, security=self.security1,
                                      day=date.today() - timedelta(days=1),
                                      qty=100, price=310, exch=1.15, cad=356.5, value=35650, type='Stock')
        today2 = HoldingDetail(account=self.account1, security=self.security2, day=date.today(),
                              qty=500, price=300, exch=1.2, cad=360, value=180000, type='Stock')
        yesterday2 = HoldingDetail(account=self.account1, security=self.security2,
                                      day=date.today() - timedelta(days=1),
                                      qty=100, price=310, exch=1.15, cad=356.5, value=35650, type='Stock')
        today3 = HoldingDetail(account=self.account2, security=self.security2, day=date.today(),
                              qty=100, price=55, exch=1.2, cad=66, value=6600, type='Stock')

        change = 0 - yesterday
        change2 = today2 - yesterday2
        change3 = today3 - 0
        total_change = sum((change, change2, change3))

        self.assertEqual(total_change.value, change.value+change2.value+change3.value)
        self.assertEqual(total_change.value_delta, change.value_delta+change2.value_delta+change3.value_delta)


class TemplateTagTestCase(SimpleTestCase):
    def test_normalize_1(self):
        self.assertEqual(mytags.normalize(Decimal('1.35'), 0, 2), '1.35')

    def test_normalize_2(self):
        self.assertEqual(mytags.normalize(Decimal('1.36'), 0, 1), '1.4')

    def test_normalize_3(self):
        self.assertEqual(mytags.normalize(Decimal('1.3'), 2, 4), '1.30')

    def test_normalize_4(self):
        self.assertEqual(mytags.normalize('1.23456', 2, 4), '1.2346')

    def test_normalize_5(self):
        self.assertEqual(mytags.normalize('1.23456', 0, 2), '1.23')

    def test_normalize_6(self):
        self.assertEqual(mytags.normalize(Decimal('1'), 0, 2), '1')

    def test_normalize_7(self):
        self.assertEqual(mytags.normalize(Decimal('0.01'), 0, 1), '0')

    def test_normalize_8(self):
        self.assertEqual(mytags.normalize(Decimal('12.1'), 0, 0), '12')

    def test_normalize_9(self):
        self.assertEqual(mytags.normalize(1.2, 4, 6), '1.2000')

    def test_drop_trailing_1(self):
        self.assertEqual(mytags.drop_trailing(Decimal('1.35'), 2), '1.35')

    def test_drop_trailing_2(self):
        self.assertEqual(mytags.drop_trailing(Decimal('1.36'), 1), '1.36')

    def test_drop_trailing_3(self):
        self.assertEqual(mytags.drop_trailing(Decimal('1.3'), 2), '1.30')

    def test_drop_trailing_4(self):
        self.assertEqual(mytags.drop_trailing('1.23456', 4), '1.23456')

    def test_drop_trailing_5(self):
        self.assertEqual(mytags.drop_trailing('1.23400', 4), '1.2340')

    def test_drop_trailing_6(self):
        self.assertEqual(mytags.drop_trailing(Decimal('1'), 0), '1')

    def test_drop_trailing_7(self):
        self.assertEqual(mytags.drop_trailing(Decimal('1.000'), 1), '1.0')

    def test_drop_trailing_8(self):
        self.assertEqual(mytags.drop_trailing(Decimal('1.000'), 0), '1')

    def test_drop_trailing_9(self):
        self.assertEqual(mytags.drop_trailing(40, 2), '40.00')

    def test_drop_trailing_10(self):
        self.assertEqual(mytags.drop_trailing(40, 0), '40')

    def test_drop_trailing_11(self):
        self.assertEqual(mytags.drop_trailing(4000, 0), '4000')


class UrlTestCase(TestCase):
    def test_responses(self):
        for i, url in enumerate(urlpatterns):
            with self.subTest(i=i):
                response = self.client.get(reverse('finance:' + url.name))
                self.assertEqual(response.status_code, 200)
