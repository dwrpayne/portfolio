from django.db import models
from django.conf import settings
from datetime import date, timedelta
import requests
import pandas
from decimal import Decimal
from dateutil import parser
from pandas_datareader import data as pdr
from pandas_datareader.exceptions import UnstableAPIWarning
from polymorphic.models import PolymorphicModel
from polymorphic.showfields import ShowFieldTypeAndContent
from ratelimit import rate_limited


class DataSourceMixin(ShowFieldTypeAndContent, PolymorphicModel):
    """
    A mixin class for retrieving data in a well-defined format.
    Just need to override a function that grabs the data.
    """
    PRIORITY_HIGH = 30
    PRIORITY_MEDIUM = 20
    PRIORITY_LOW = 10
    priority = models.IntegerField(default=PRIORITY_MEDIUM)

    def _Retrieve(self, start, end):
        """
        Given datetime.date 'start' and 'end', return a pandas series of price values.
        """
        return pandas.Series()


class ConstantDataSource(DataSourceMixin):
    value = models.DecimalField(max_digits=19, decimal_places=6, default=1)

    def __str__(self):
        return "Constant value of {}".format(self.value)

    def __repr__(self):
        return "FakeDataSource<{}>".format(self.value)

    def _Retrieve(self, start, end):
        return pandas.Series([self.value], index=pandas.date_range(start, end))


class PandasDataSource(DataSourceMixin):
    symbol = models.CharField(max_length=32, default=None)
    source = models.CharField(max_length=32, default=None)
    column = models.CharField(max_length=32, default=None)

    @classmethod
    def create_bankofcanada(cls, currency_code):
        symbol = "FXCAD{}".format(currency_code)
        return cls.objects.create(symbol=symbol, source='bankofcanada', column=symbol)

    @classmethod
    def create_stock(cls, symbol):
        return cls.objects.create(symbol=symbol, source='google', column='Close')

    def __str__(self):
        return "Pandas {} for {}".format(self.source, self.symbol)

    def __repr__(self):
        return "PandasDataSource<{},{},{}>".format(self.symbol, self.source, self.column)

    def _Retrieve(self, start, end):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', category=UnstableAPIWarning, lineno=40)
            df = pdr.DataReader(self.symbol, self.source, start, end)
        if df.empty:
            return []
        return pandas.Series(df[self.column], df.index)


class AlphaVantageStockSource(DataSourceMixin):
    api_key = models.CharField(max_length=32, default=settings.ALPHAVANTAGE_KEY)
    symbol = models.CharField(max_length=32)

    def __str__(self):
        return "AlphaVantageStock source for {}".format(self.symbol)

    def __repr__(self):
        return "AlphaVantageStockSource<{}>".format(self.symbol)

    def validate_symbol(self):
        """Go through our list of possible symbol transformations to find one that has data in the last week"""
        original_symbol = self.symbol
        possible_symbols = [self.symbol, self.symbol + '.TO', self.symbol.replace('.', '-') + '.TO']

        for symbol in possible_symbols:
            self.symbol = symbol
            if self._Retrieve(date.today() - timedelta(days=7), date.today()):
                return
        self.symbol = 'NO VALID LOOKUP FOR {}'.format(original_symbol)

    @rate_limited(1,2)
    def _Retrieve(self, start, end):
        params = {'function': 'TIME_SERIES_DAILY', 'apikey': self.api_key,
                  'symbol': self.symbol}
        if (date.today() - start).days >= 100:
            params['outputsize'] = 'full'

        r = requests.get('https://www.alphavantage.co/query', params=params)
        if r.ok:
            json = r.json()
            try:
                data = {parser.parse(day).date(): Decimal(vals['4. close']) for day, vals in
                        json['Time Series (Daily)'].items() if str(start) <= day <= str(end)}
                return pandas.Series(data)
            except KeyError:
                pass

        print('Failed to get data, response: {}'.format(r.content))
        return pandas.Series()


class AlphaVantageCurrencySource(DataSourceMixin):
    api_key = models.CharField(max_length=32, default=settings.ALPHAVANTAGE_KEY)
    from_symbol = models.CharField(max_length=32)
    to_symbol = models.CharField(max_length=32, default='CAD')

    def __str__(self):
        return "AlphaVantageCurrency source for {} to {}".format(self.from_symbol, self.to_symbol)

    def __repr__(self):
        return "AlphaVantageCurrencySource<{},{}>".format(self.from_symbol, self.to_symbol)

    @rate_limited(1,2)
    def _Retrieve(self, start, end):
        params = {'function': 'CURRENCY_EXCHANGE_RATE', 'apikey': self.api_key,
                  'from_currency': self.from_symbol, 'to_currency': self.to_symbol}

        response = requests.get('https://www.alphavantage.co/query', params=params)
        if response.ok:
            json = response.json()
            try:
                price = Decimal(json['Realtime Currency Exchange Rate']['5. Exchange Rate'])
                return pandas.Series(data=[price], index=[date.today()])
            except KeyError:
                pass

        print('Failed to get data, response: {}'.format(response.content))
        return pandas.Series()


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
            return pandas.Series({parser.parse(item['d']).date(): Decimal(item['v'])
                                   for item in json['data']['Prices']})
        return pandas.Series()


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
        return series.interpolate()[start:end]
