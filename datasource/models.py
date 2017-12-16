from django.db import models
import datetime
import requests
import pandas
from decimal import Decimal
from dateutil import parser
from pandas_datareader import data as pdr
from polymorphic.models import PolymorphicModel

class DataSourceMixin(PolymorphicModel):
    """
    A mixin class for retrieving data in a well-defined format.
    Just need to override a function that grabs the data.
    """

    @staticmethod
    def ProcessRateData(data, end_date):
        """ Expects an iterator of day, price pairs"""
        dates_and_prices = list(zip(*data))
        if len(dates_and_prices) == 0:
            return []

        dates, prices = dates_and_prices
        data = pandas.Series(prices, index=dates, dtype='float64')

        data = data.sort_index()
        index = pandas.DatetimeIndex(start=min(data.index), end=end_date, freq='D').date
        data = data.reindex(index).ffill()
        return data.iteritems()

    def GetData(self, start, end):
        return self.ProcessRateData(self._Retrieve(start, end))

    def _Retrieve(self, start, end):
        """
        Given datetime.date 'start' and 'end', return
        an iterator of (datetime.date, price) pairs.
        This is the only function you should override.
        """
        return []


class FakeDataSource(DataSourceMixin):
    value = models.DecimalField(max_digits=19, decimal_places=6)

    def _Retrieve(self, start, end):
        for day in pandas.date_range(start, end).date:
            yield day, self.value

class PandasDataSource(DataSourceMixin):
    symbol = models.CharField(max_length=32, default=None)
    source = models.CharField(max_length=32, default=None)
    column = models.CharField(max_length=32, default=None)

    def _Retrieve(self, start, end):
        df = pdr.DataReader(self.symbol, self.source, start, end)
        if df.empty:
            return []
        return pandas.Series(df[self.column], df.index)

class AlphaVantageDataSource(DataSourceMixin):
    api_key = models.CharField(max_length=32, default='P38D2XH1GFHST85V')
    function = models.CharField(max_length=32, default='TIME_SERIES_DAILY')
    symbol = models.CharField(max_length=32)

    def _Retrieve(self, start, end):
        # TODO: Monster hack for DLR - should be a fakedatasource
        if self.symbol == 'DLR.U.TO':
            index = pandas.date_range(start, end, freq='D').date
            return zip(index, pandas.Series(10.0, index))

        params = {'function': self.function,
                  'symbol': self.symbol, 'apikey': self.api_key}
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

    def _Retrieve(self, start, end):
        url = self.raw_url.format(self.symbol, str(start), str(end))
        r = requests.get(url)
        json = r.json()
        if 'data' in json and 'Prices' in json['data']:
            return [(parser.parse(item['d']).date(), Decimal(item['v'])) for item in json['data']['Prices']]
        return []

