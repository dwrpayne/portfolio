# Create your tests here.
from django.test import TestCase
from datasource.models import DataSourceMixin
from datetime import date

class DataSourceMixinTestCase(TestCase):

    def test_process_basic(self):
        pairs = [(date(2017, 1, 1), 12.34), (date(2017, 1, 2), 12.12),
                 (date(2017, 1, 3), 12.98), (date(2017, 1, 4), 13.50)]
        series = list(DataSourceMixin._ProcessRateData(pairs, date(2017, 1, 4)))
        self.assertEqual(series, pairs)

    def test_process_gaps(self):
        pairs = [(date(2017, 1, 1), 12.34), (date(2017, 1, 3), 12.98), (date(2017, 1, 4), 13.50)]
        series = list(DataSourceMixin._ProcessRateData(pairs, date(2017, 1, 4)))
        self.assertEqual(series[0], pairs[0])
        self.assertEqual(series[1], (date(2017, 1, 2), 12.34))
        self.assertEqual(series[2], pairs[1])
        self.assertEqual(series[3], pairs[2])

        


