"""
This file demonstrates writing tests using the unittest module. These will pass
when you run "manage.py test".

Replace this with more appropriate tests for your application.
"""

from django.test import TestCase
from .models import Security, Currency, DataProvider
import pandas
import datetime


def setUpModule():
    Currency.objects.create(code='CAD')
    Currency.objects.create(code='USD')
    #QuestradeClient.CreateClient('test', '123457890')

def tearDownModule():
    Security.objects.all().delete()

class RateLookupMixinTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tsla = Security.objects.create(symbol='TSLA', currency_id='USD', lookupColumn='Close', lookupSymbol='TSLA', lookupSource='yahoo')

    @classmethod
    def tearDownClass(cls):
        Security.objects.all().delete()

    def check_process_rate_data_extend(self, input):
        data = self.tsla._ProcessRateData(input, datetime.date(2014, 1, 7))
        self.assertEqual(len(list(data)), 7)

    def check_process_rate_data_ffill(self, input):
        data = self.tsla._ProcessRateData(input, datetime.date(2014, 1, 6))
        self.assertIn((datetime.date(2014, 1, 5), 15), list(data))

    def check_process_rate_data_works(self, input):
        data = self.tsla._ProcessRateData(input, datetime.date(2014, 1, 6))
        self.assertIn((datetime.date(2014, 1, 1), 12), list(data))

    def test_process_rate_data_iterator_extend(self):
        pairs = [(datetime.date(2014, 1, 1), 12),  (datetime.date(2014, 1, 2), 13),   (datetime.date(2014, 1, 4), 15),  (datetime.date(2014, 1, 6), 19)]
        self.check_process_rate_data_extend(pairs)

    def test_process_rate_data_iterator_ffill(self):
        pairs = [(datetime.date(2014, 1, 1), 12),  (datetime.date(2014, 1, 2), 13),   (datetime.date(2014, 1, 4), 15),  (datetime.date(2014, 1, 6), 19)]
        self.check_process_rate_data_ffill(pairs)

    def test_process_rate_data_iterator_works(self):
        pairs = [(datetime.date(2014, 1, 1), 12),  (datetime.date(2014, 1, 2), 13),   (datetime.date(2014, 1, 4), 15),  (datetime.date(2014, 1, 6), 19)]
        self.check_process_rate_data_works(pairs)

    def test_process_rate_data_dataframe_extend(self):
        frame = pandas.DataFrame({'open': [10, 20, 30, 40], 'Close': [12, 13, 15, 19], 'vol': [100, 200, 300, 400]}, [datetime.date(2014, 1, 1), datetime.date(2014, 1, 2), datetime.date(2014, 1, 4), datetime.date(2014, 1, 6)])
        self.check_process_rate_data_extend(frame)

    def test_process_rate_data_dataframe_ffill(self):
        frame = pandas.DataFrame({'open': [10, 20, 30, 40], 'Close': [12, 13, 15, 19], 'vol': [100, 200, 300, 400]}, [datetime.date(2014, 1, 1), datetime.date(2014, 1, 2), datetime.date(2014, 1, 4), datetime.date(2014, 1, 6)])
        self.check_process_rate_data_ffill(frame)

    def test_process_rate_data_dataframe_works(self):
        frame = pandas.DataFrame({'open': [10, 20, 30, 40], 'Close': [12, 13, 15, 19], 'vol': [100, 200, 300, 400]}, [datetime.date(2014, 1, 1), datetime.date(2014, 1, 2), datetime.date(2014, 1, 4), datetime.date(2014, 1, 6)])
        self.check_process_rate_data_works(frame)

    def get_data(self, lookup, start, end):
        yield datetime.date(2014, 1, 1), 12
        yield datetime.date(2014, 1, 2), 13
        yield datetime.date(2014, 1, 4), 15
        yield datetime.date(2014, 1, 6), 19

    def test_sync_rates_extending(self):
        self.tsla.SyncRates(self.get_data)
        self.assertEqual(self.tsla.rates.all().count(), (datetime.date.today() - datetime.date(2014, 1, 1)).days+1)

    def test_sync_rates_today(self):
        self.tsla.SyncRates(DataProvider._RetrieveData)
        self.assertEqual(self.tsla.rates.latest().day, datetime.date.today())

    def test_sync_rates_idempotent(self):
        self.tsla.SyncRates(DataProvider._RetrieveData)
        count = self.tsla.rates.all().count()
        self.tsla.SyncRates(DataProvider._RetrieveData)
        self.assertEqual(count, self.tsla.rates.all().count())

class SecurityModelTests(TestCase):
    @classmethod
    def setUpClass(cls):
        Security.objects.create(symbol='TSLA', currency_id='USD')
        Security.objects.create(symbol='MSFT', currency_id='USD')
        Security.objects.create(symbol='VUN.TO', currency_id='CAD')
        Security.objects.create(symbol='ATVI  23400827IU4', currency_id='USD', type=Security.Type.Option)

    @classmethod
    def tearDownClass(cls):
        Security.objects.all().delete()

    def test_manager_objects(self):
        self.assertEqual(len(Security.objects.all()), 4)

    def test_manager_stocks(self):
        self.assertEqual(len(Security.stocks.all()), 3)


