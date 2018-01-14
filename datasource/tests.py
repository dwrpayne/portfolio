# Create your tests here.
from django.test import TestCase
from datasource.models import *
from datetime import date

class DataSourceMixinTestCase(TestCase):
    def test_process_basic(self):
        pairs = [(date(2017, 1, 1), 12.34), (date(2017, 1, 2), 12.12),
                 (date(2017, 1, 3), 12.98), (date(2017, 1, 4), 13.50)]
        series = list(DataSourceMixin._ProcessRateData(pairs, date(2017, 1, 1), date(2017, 1, 4)))
        self.assertEqual(series, pairs)

    def test_process_gaps(self):
        pairs = [(date(2017, 1, 1), 12.34), (date(2017, 1, 3), 12.98), (date(2017, 1, 4), 13.50)]
        series = list(DataSourceMixin._ProcessRateData(pairs, date(2017, 1, 1), date(2017, 1, 4)))
        self.assertEqual(series[0], pairs[0])
        self.assertEqual(series[1], (date(2017, 1, 2), 12.34))
        self.assertEqual(series[2], pairs[1])
        self.assertEqual(series[3], pairs[2])

    def test_process_end_date(self):
        pairs = [(date(2017, 1, 1), 12.34), (date(2017, 1, 3), 12.98), (date(2017, 1, 4), 13.50)]
        series = list(DataSourceMixin._ProcessRateData(pairs, date(2017, 1, 1), date(2017, 1, 3)))
        self.assertEqual(series[0], pairs[0])
        self.assertEqual(series[1], (date(2017, 1, 2), 12.34))
        self.assertEqual(series[2], pairs[1])
        self.assertEqual(len(series), 3)

    def test_process_start_date(self):
        pairs = [(date(2017, 1, 2), 12.34), (date(2017, 1, 3), 12.98), (date(2017, 1, 4), 13.50)]
        series = list(DataSourceMixin._ProcessRateData(pairs, date(2017, 1, 1), date(2017, 1, 3)))
        self.assertEqual(series[0], (date(2017, 1, 1), 12.34))
        self.assertEqual(series[1], (date(2017, 1, 2), 12.34))
        self.assertEqual(series[2], pairs[1])
        self.assertEqual(len(series), 3)


class ConstantDataSourceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.datasource = ConstantDataSource(value=2)

    def test_basic(self):
        data = self.datasource.GetData(date(2017, 1, 1), date(2017, 1, 4))
        dates, values = list(zip(*data))
        self.assertSequenceEqual(values, [2.0]*4)


class PandasDataSourceTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        bankofcanada = PandasDataSource.create_bankofcanada('USD')
        cls.bocdata = list(bankofcanada.GetData(date(2018, 1, 1), date(2018, 1, 6)))

    def test_boc_data(self):
        dates, values = list(zip(*self.bocdata))
        rounded = [round(v, 5) for v in values]
        self.assertSequenceEqual(rounded, [.79891, .79789, .79904, .80626, .80626])

    def test_boc_date(self):
        self.assertEqual(self.bocdata[-1][0], date(2018, 1, 6))


class AlphavantageDataSourceTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        tsla = AlphaVantageDataSource.objects.create(symbol='TSLA')
        cls.bocdata = list(tsla.GetData(date(2018, 1, 1), date(2018, 1, 6)))

    def test_boc_data(self):
        dates, values = list(zip(*self.bocdata))
        rounded = [round(v, 5) for v in values]
        self.assertSequenceEqual(rounded, [.79891, .79789, .79904, .80626, .80626])

    def test_boc_date(self):
        self.assertEqual(self.bocdata[-1][0], date(2018, 1, 6))



