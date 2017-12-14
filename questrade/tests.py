from django.test import TestCase

from .models import QuestradeClient, QuestradeAccount
from finance.models import Security, Currency, Activity, ExchangeRate, DataProvider
from decimal import Decimal
import datetime
import unittest


def setUpModule():
    Security.objects.all().delete()
    QuestradeClient.objects.all().delete()

    Currency.objects.create(code='CAD', rateLookup='CADBASE')
    Currency.objects.create(code='USD', rateLookup='DEXCAUS')
    # QuestradeClient.CreateClient('test', '123457890')


def tearDownModule():
    pass


@unittest.skip('No QuestradeClient API support outside production')
class ClientModelTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = QuestradeClient.objects.get(username='David')
        cls.client.Authorize()

    @classmethod
    def tearDownClass(cls):
        cls.client.CloseSession()

    def test_make_security(self):
        self.client.EnsureSecuritiesExist([38526])
        s = Security.objects.get(symbolid=38526)
        self.assertEqual(str(s.symbol), 'TSLA')

    def test_make_security_preexisting(self):
        self.client.EnsureSecuritiesExist([38526])
        self.client.EnsureSecuritiesExist([38526, 8049])
        self.assertEqual(len(Security.objects.all()), 2)


class ActivityModelTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cad = Currency.objects.get(code='CAD')
        cls.vti = Security.objects.create(symbol='VTI', currency_id='USD')
        json = {'tradeDate': '2013-07-29T00:00:00.000000-04:00', 'transactionDate': '2013-08-01T00:00:00.000000-04:00', 'settlementDate': '2013-08-01T00:00:00.000000-04:00', 'action': 'Buy',
                'symbol': 'VTI', 'symbolId': 40571, 'description': '', 'currency': 'USD', 'quantity': 11, 'price': 87.12, 'grossAmount': -958.32, 'commission': 0, 'netAmount': -958.32, 'type': 'Trades'}
        c = QuestradeClient.objects.create(username='test', refresh_token='test_token')
        a = QuestradeAccount.objects.create(client=c, id=0, type='')
        cls.buy = Activity.CreateFromJson(json, a)

        json = {'tradeDate': '2013-07-23T00:00:00.000000-04:00', 'transactionDate': '2013-07-23T00:00:00.000000-04:00', 'settlementDate': '2013-07-23T00:00:00.000000-04:00', 'action': 'DEP',
                'symbol': 'CAD', 'symbolId': 0, 'description': '2666275025 CUCBC DIR DEP', 'currency': 'CAD', 'quantity': 0, 'price': 0, 'grossAmount': 0, 'commission': 0, 'netAmount': 1000, 'type': 'Deposits'}
        cls.dep = Activity.CreateFromJson(json, a)

    @classmethod
    def tearDownClass(cls):
        Currency.objects.all().delete()
        QuestradeClient.objects.all().delete()
        Security.objects.all().delete()
        Activity.objects.all().delete()
        ExchangeRate.objects.all().delete()

    def test_buy_quantity(self):
        self.assertEqual(self.buy.qty, 11)

    def test_buy_price(self):
        self.assertEqual(self.buy.price, Decimal('87.12'))

    def test_buy_effect_cash(self):
        self.assertEqual(self.buy.GetHoldingEffect()['CashUSD'], Decimal('-958.32'))

    def test_dep_effect_cash_2(self):
        self.assertNotIn('USD', self.dep.GetHoldingEffect())

    def test_buy_effect_stock(self):
        self.assertEqual(self.buy.GetHoldingEffect()['VTI'], 11)

    def test_buy_security(self):
        self.assertEqual(self.buy.security, self.vti)

    def test_buy_currency(self):
        self.assertEqual(self.buy.currency, 'CashUSD')

    def test_dep_quantity(self):
        self.assertEqual(self.dep.qty, 0)

    def test_dep_price(self):
        self.assertEqual(self.dep.price, 0)

    def test_dep_effect_cash(self):
        self.assertEqual(self.dep.GetHoldingEffect()['CashCAD'], 1000)

    def test_dep_effect_cash_3(self):
        self.assertNotIn('CAD', self.dep.GetHoldingEffect())

    def test_dep_security(self):
        self.assertEqual(self.dep.security, self.cad)


class AccountModelTests(TestCase):
    @classmethod
    def setUpClass(cls):
        c = QuestradeClient.objects.create(username='test', refresh_token='test_token')
        cls.account = QuestradeAccount.objects.create(client=c, id=0, type='')
        Security.objects.create(symbol='VTI', currency_id='USD')
        DataProvider.SyncAllSecurities()
        json = {'tradeDate': '2013-07-13T00:00:00.000000-04:00', 'transactionDate': '2013-07-13', 'settlementDate': '2013-07-13', 'action': 'DEP', 'symbol': 'CAD', 'symbolId': 0,
                'description': '2666275025 CUCBC DIR DEP', 'currency': 'CAD', 'quantity': 0, 'price': 0, 'grossAmount': 0, 'commission': 0, 'netAmount': 1000, 'type': 'Deposits'}
        Activity.CreateFromJson(json, cls.account)
        json = {'tradeDate': '2013-07-23T00:00:00.000000-04:00', 'transactionDate': '2013-07-23', 'settlementDate': '2013-07-23', 'action': 'DEP', 'symbol': 'USD', 'symbolId': 0,
                'description': '2666275025 CUCBC DIR DEP', 'currency': 'USD', 'quantity': 0, 'price': 0, 'grossAmount': 0, 'commission': 0, 'netAmount': 1000, 'type': 'Deposits'}
        Activity.CreateFromJson(json, cls.account)
        json = {'tradeDate': '2013-07-29T00:00:00.000000-04:00', 'transactionDate': '2013-08-01', 'settlementDate': '2013-08-01', 'action': 'Buy', 'symbol': 'VTI',
                'symbolId': 40571, 'description': '', 'currency': 'USD', 'quantity': 11, 'price': 87.12, 'grossAmount': -958.32, 'commission': 0, 'netAmount': -958.32, 'type': 'Trades'}
        Activity.CreateFromJson(json, cls.account)
        cls.account.RegenerateDBHoldings()

    @classmethod
    def tearDownClass(cls):
        Currency.objects.all().delete()
        Security.objects.all().delete()
        QuestradeClient.objects.all().delete()
        ExchangeRate.objects.all().delete()

    def test_recent_activity(self):
        self.assertEqual(self.account.GetMostRecentActivityDate(), datetime.date(2013, 7, 29))

    def test_value_before(self):
        self.assertEqual(self.account.GetValueAtDate('2011-01-01'), 0)

    def test_value_after_1(self):
        self.assertEqual(self.account.GetValueAtDate('2013-07-15'), 1000)

    def test_value_after_2(self):
        self.assertEqual(self.account.GetValueAtDate('2013-07-25'), Decimal('2028.3'))

    def test_value_after_3(self):
        self.assertEqual(self.account.GetValueAtDate('2013-07-30'), Decimal('2031.577452'))

    def test_value_after_4(self):
        self.assertEqual(self.account.GetValueAtDate('2014-07-15'), Decimal('2252.46261'))


class SecurityModelTests(TestCase):
    @classmethod
    def setUpClass(cls):
        Security.objects.create(symbol='TSLA', currency_id='USD')
        Security.objects.create(symbol='MSFT', currency_id='USD')
        Security.objects.create(symbol='VUN.TO', currency_id='CAD')
        Security.objects.create(symbol='ATVI  23400827IU4',
                                currency_id='USD', type=Security.Type.Option)

    @classmethod
    def tearDownClass(cls):
        Currency.objects.all().delete()
        Security.objects.all().delete()
        ExchangeRate.objects.all().delete()

    def test_manager_objects(self):
        self.assertEqual(len(Security.objects.all()), 4)

    def test_manager_stocks(self):
        self.assertEqual(len(Security.stocks.all()), 3)


class DataProviderTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cad = Currency.objects.get(code='CAD')
        cls.usd = Currency.objects.get(code='USD')
        cls.tsla = Security.objects.create(symbol='TSLA', currency_id='USD')
        DataProvider.SyncAllSecurities()

    @classmethod
    def tearDownClass(cls):
        Currency.objects.all().delete()
        Security.objects.all().delete()
        ExchangeRate.objects.all().delete()

    def test_exchange_rates_holiday(self):
        self.assertEqual(DataProvider.GetExchangeRate('USD', '2015-01-01'), Decimal('1.160100'))

    def test_exchange_rates_normal_1(self):
        self.assertEqual(DataProvider.GetExchangeRate('USD', '2014-12-31'), Decimal('1.160100'))

    def test_exchange_rates_normal_2(self):
        self.assertEqual(DataProvider.GetExchangeRate('USD', '2014-12-30'), Decimal('1.159700'))

    def test_exchange_rates_up_to_date(self):
        self.assertTrue(datetime.date.today() - self.usd.GetLatestEntry()
                        < datetime.timedelta(days=14))

    def test_stock_price_up_to_date(self):
        self.assertTrue(datetime.date.today() - self.tsla.GetLatestEntry()
                        < datetime.timedelta(days=5))

    def test_stock_price_holiday(self):
        self.assertEqual(self.tsla.GetPrice('2015-01-01'), Decimal('222.41'))

    def test_stock_price_normal_1(self):
        self.assertEqual(self.tsla.GetPrice('2014-12-31'), Decimal('222.41'))

    def test_stock_price_normal_2(self):
        self.assertEqual(self.tsla.GetPrice('2014-12-30'), Decimal('222.23'))

    def test_stock_price_exch_holiday_both(self):
        self.assertEqual(self.tsla.GetPriceCAD('2015-01-01'), Decimal('258.017841'))

    def test_stock_price_exch_normal_1(self):
        self.assertEqual(self.tsla.GetPriceCAD('2014-12-31'), Decimal('258.017841'))

    def test_stock_price_exch_normal_2(self):
        self.assertEqual(self.tsla.GetPriceCAD('2014-12-30'), Decimal('257.720131'))

    def test_stock_price_exch_holiday_one(self):
        self.assertEqual(self.tsla.GetPriceCAD('2014-12-26'), Decimal('264.749622'))
