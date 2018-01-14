from django.db import models
import datetime
import requests
import pandas
from decimal import Decimal
from dateutil import parser
from pandas_datareader import data as pdr
from polymorphic.models import PolymorphicModel
from polymorphic.showfields import ShowFieldTypeAndContent

class DataSourceMixin(ShowFieldTypeAndContent, PolymorphicModel):
    """
    A mixin class for retrieving data in a well-defined format.
    Just need to override a function that grabs the data.
    """

    @classmethod
    def _ProcessRateData(cls, pairs, start_date, end_date):
        """ Expects an iterator of day, price pairs"""
        dates_and_prices = list(zip(*pairs))
        if len(dates_and_prices) == 0:
            return []

        dates, prices = dates_and_prices
        series = pandas.Series(prices, index=dates, dtype='float64')

        series = series.sort_index()
        index = pandas.DatetimeIndex(start=start_date, end=end_date, freq='D').date
        series = series.reindex(index).fillna(method='ffill').fillna(method='bfill')
        return series.iteritems()

    def GetData(self, start, end):
        print("Getting data from {} for {} to {}".format(self, start, end))
        data = self._Retrieve(start, end)
        return self._ProcessRateData(data, start, end)

    def _Retrieve(self, start, end):
        """
        Given datetime.date 'start' and 'end', return
        an iterator of (datetime.date, price) pairs.
        This is the only function you need to override.
        """
        return []


class ConstantDataSource(DataSourceMixin):
    value = models.DecimalField(max_digits=19, decimal_places=6, default=1)

    def __str__(self):
        return "Constant value of {}".format(self.value)

    def __repr__(self):
        return "FakeDataSource<{}>".format(self.value)

    def _Retrieve(self, start, end):
        for day in pandas.date_range(start, end).date:
            yield day, self.value

class PandasDataSource(DataSourceMixin):
    symbol = models.CharField(max_length=32, default=None)
    source = models.CharField(max_length=32, default=None)
    column = models.CharField(max_length=32, default=None)

    @classmethod
    def create_bankofcanada(cls, currency_code):
        source = 'bankofcanada'
        symbol = "FX{}CAD".format(currency_code)
        return cls.objects.create(symbol=symbol, source=source, column=symbol)

    def __str__(self):
        return "Pandas {} for {}".format(self.source, self.symbol)

    def __repr__(self):
        return "PandasDataSource<{},{},{}>".format(self.symbol, self.source, self.column)

    def _Retrieve(self, start, end):
        df = pdr.DataReader(self.symbol, self.source, start, end)
        if df.empty:
            return []
        if self.source == 'bankofcanada':
            df = 1/df
        return pandas.Series(df[self.column], df.index).iteritems()

class AlphaVantageDataSource(DataSourceMixin):
    api_key = models.CharField(max_length=32, default='P38D2XH1GFHST85V')
    function = models.CharField(max_length=32, default='TIME_SERIES_DAILY')
    symbol = models.CharField(max_length=32)

    def __str__(self):
        return "AlphaVantage {} for {}".format(self.function, self.symbol)

    def __repr__(self):
        return "AlphaVantageDataSource<{}>".format(self.symbol)

    def _Retrieve(self, start, end):
        params = {'function': self.function, 'apikey': self.api_key,
                  'symbol': self.symbol}
        if (datetime.date.today() - start).days >= 100:
            params['outputsize'] = 'full'

        r = requests.get('https://www.alphavantage.co/query', params=params)
        if r.ok:
            json = r.json()
            if 'Time Series (Daily)' in json:
                return [(parser.parse(day).date(), Decimal(vals['4. close'])) for day, vals in
                        json['Time Series (Daily)'].items() if str(start) <= day <= str(end)]
        else:
            print('Failed to get data, response: {}'.format(r.content))
        return []


class MorningstarDataSource(DataSourceMixin):
    raw_url = models.CharField(max_length=1000, default='https://api.morningstar.com/service/mf/Price/Mstarid/{}?format=json&username=morningstar&password=ForDebug&startdate={}&enddate={}')
    symbol = models.CharField(max_length=32, default=None)

    def __str__(self):
        return "Morningstar {}".format(self.symbol)

    def __repr__(self):
        return "MorningstarDataSource<{}>".format(self.symbol)

    def _Retrieve(self, start, end):
        url = self.raw_url.format(self.symbol, str(start), str(end))
        r = requests.get(url)
        json = r.json()
        if 'data' in json and 'Prices' in json['data']:
            return [(parser.parse(item['d']).date(), Decimal(item['v'])) for item in json['data']['Prices']]
        return []


class InterpolatedDataSource(DataSourceMixin):
    start_day = models.DateField()
    start_val = models.DecimalField(max_digits=19, decimal_places=6)
    end_day = models.DateField()
    end_val = models.DecimalField(max_digits=19, decimal_places=6)

    def __str__(self):
        return "interpolated data from {} {} to {} {}".format(
            self.start_day, self.start_val, self.end_day, self.end_val)

    def __repr__(self):
        return "InterpolatedDataSource<{},{},{},{}>".format(
            self.start_day, self.start_val, self.end_day, self.end_val)

    def _Retrieve(self, start, end):
        series = pandas.Series(index=pandas.date_range(self.start_day, self.end_day))
        series[self.start_day] = self.start_val
        series[self.end_day] = self.end_val
        return series.interpolate()[start:end].iteritems()
