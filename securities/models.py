import datetime
from decimal import Decimal

from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction, connection
from django.db.models import F
from django.utils.functional import cached_property

from datasource.models import DataSourceMixin

import pandas
import requests
from dateutil import parser
from model_utils import Choices
from pandas_datareader import data as pdr



class RateHistoryTableMixin(models.Model):
    """
    A mixin class for storing rate history.
    Classes that use this must define a foreign key back to the related RateLookupMixin with related_name="rates"
    """
    day = models.DateField(default=datetime.date.today)
    price = models.DecimalField(max_digits=19, decimal_places=6)

    class Meta:
        abstract = True


# noinspection PyUnresolvedReferences,PyUnresolvedReferences,PyUnresolvedReferences
class RateLookupMixin(models.Model):
    """
    A mixin class that adds the necessary fields to support looking up historical rates from pandas-datareader
    Classes that use this must define a subclass of RateHistoryTableMixin and create a foreign key back to this class with related_name="rates"
    """
    lookupSymbol = models.CharField(max_length=32, null=True, blank=True, default=None)
    lookupSource = models.CharField(max_length=32, null=True, blank=True, default=None)
    lookupColumn = models.CharField(max_length=32, null=True, blank=True, default=None)
    datasource = models.ForeignKey(DataSourceMixin, null=True, blank=True,
                                   default=None, on_delete=models.DO_NOTHING)

    class Meta:
        abstract = True

    @property
    def earliest_price_needed(self):
        return datetime.date(2009, 1, 1)

    @property
    def latest_price_needed(self):
        return datetime.date.today()

    def GetShouldSyncRange(self):
        """ Returns a pair (start,end) of datetime.dates that need to be synced."""
        try:
            earliest = self.rates.earliest().day
            latest = self.rates.latest().day
        except ObjectDoesNotExist:
            return self.earliest_price_needed, self.latest_price_needed

        if earliest > self.earliest_price_needed:
            return self.earliest_price_needed - datetime.timedelta(days=7), self.latest_price_needed

        if latest < self.latest_price_needed:
            return latest - datetime.timedelta(days=7), self.latest_price_needed

        return None, None

    @property
    def live_price(self):
        try:
            return self.rates.get(day=datetime.date.today()).price
        except:
            return self.rates.latest().price

    @live_price.setter
    def live_price(self, value):
        self.rates.update_or_create(day=datetime.date.today(), defaults={'price': value})

    def _ProcessRateData(self, data, end_date):
        if isinstance(data, pandas.DataFrame):
            if data.empty:
                return []
            data = pandas.Series(data[self.lookupColumn], data.index)
        else:
            # Expect iterator of day, price pairs
            dates_and_prices = list(zip(*data))
            if len(dates_and_prices) == 0:
                return []

            dates, prices = dates_and_prices
            data = pandas.Series(prices, index=dates, dtype='float64')

        data = data.sort_index()
        index = pandas.DatetimeIndex(start=min(data.index), end=end_date, freq='D').date
        data = data.reindex(index).ffill()
        return data.iteritems()

    def SyncRates(self, retriever_fn):
        """
        retriever_fn is the function that will retrieve the rates.
        It gets passed (self, start, end) and is expected to return an iterator of (day, price) pairs or a pandas dataframe
        """
        start, end = self.GetShouldSyncRange()
        if start is None:
            print('Already synced data for {}, skipping.'.format(self.lookupSymbol))
            return []

        print('Syncing prices for {} from {} to {}...'.format(self.lookupSymbol, start, end))

        retrieved_data = retriever_fn(start, end)
        data = self._ProcessRateData(retrieved_data, end)

        with transaction.atomic():
            for day, price in data:
                self.rates.update_or_create(day=day, defaults={'price': price})

    def GetRateOnDay(self, day):
        return self.rates.get(day=day).price

    @staticmethod
    def _FakeData(start, end, val=1.):
        for day in pandas.date_range(start, end).date:
            yield day, val


class CurrencyManager(models.Manager):
    def DefaultInit(self):
        self.create(code='CAD')
        usd = self.create(code='USD', lookupSymbol='DEXCAUS', lookupSource='fred', lookupColumn='DEXCAUS')
        usd.SyncExchangeRates()
        usd.lookupSource = 'bankofcanada'
        usd.lookupSymbol = 'FXCADUSD'
        usd.lookupColumn = 'FXCADUSD'
        usd.save()

    def create(self, code, **kwargs):
        currency = super().create(code=code, **kwargs)
        Security.objects.get_or_create(currency=currency, type=Security.Type.Cash,
                                       defaults={'symbol': code + ' Cash'})
        return currency


class Currency(RateLookupMixin):
    code = models.CharField(max_length=3, primary_key=True)
    objects = CurrencyManager()

    def __str__(self):
        return self.code

    class Meta:
        verbose_name_plural = 'Currencies'

    @property
    def cash_security(self):
        return self.security_set.get(type=Security.Type.Cash)

    def GetTodaysChange(self):
        rates = self.rates.filter(
            day__gte=datetime.date.today() - datetime.timedelta(days=1)
        ).values_list('price', flat=True)
        yesterday = 1 / rates[0]
        today = 1 / rates[1]
        return today, (today - yesterday) / yesterday

    def _RetrievePandasData(self, start, end):
        df = pdr.DataReader(self.lookupSymbol, self.lookupSource, start, end)
        if df.empty:
            return []
        return pandas.Series(df[self.lookupColumn], df.index)

    def SyncExchangeRates(self):
        self.SyncRates(self._FakeData if self.code == 'CAD' else self._RetrievePandasData)

    def SyncLive(self):
        assert self.code == 'USD'
        request = requests.get('https://openexchangerates.org/api/latest.json',
                               params={'app_id': '2f666e800586440088f5fc22d688f520', 'symbols': 'CAD'})
        self.live_price = Decimal(str(request.json()['rates']['CAD']))


class ExchangeRate(RateHistoryTableMixin):
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='rates')

    class Meta:
        unique_together = ('currency', 'day')
        get_latest_by = 'day'
        indexes = [
            models.Index(fields=['currency']),
            models.Index(fields=['day'])
        ]

    def __str__(self):
        return "{} {} {}".format(self.currency, self.day, self.price)


class SecurityManager(models.Manager):
    def Create(self, symbol, currency):
        if len(symbol) >= 20:
            return self.CreateOptionRaw(symbol, currency)
        else:
            return self.CreateStock(symbol, currency)

    def CreateStock(self, symbol, currency_str):
        return super().create(
            symbol=symbol,
            type=self.model.Type.Stock,
            currency_id=currency_str,
            lookupSymbol=symbol
        )

    def CreateOptionRaw(self, optsymbol, currency_str):
        return super().create(
            symbol=optsymbol,
            type=self.model.Type.Option,
            currency_id=currency_str
        )


class Security(RateLookupMixin):
    Type = Choices('Stock', 'Option', 'Cash', 'MutualFund')
    symbol = models.CharField(max_length=32, primary_key=True)
    description = models.CharField(max_length=500, null=True, blank=True, default='')
    type = models.CharField(max_length=12, choices=Type, default=Type.Stock)
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE)

    objects = SecurityManager()

    def __str__(self):
        return "{} {}".format(self.symbol, self.currency)

    def __repr(self):
        return "Security({} ({}) {})".format(self.symbol, self.currency, self.description)

    class Meta:
        verbose_name_plural = 'Securities'
        indexes = [
            models.Index(fields=['symbol']),
            models.Index(fields=['currency_id'])
        ]

    @cached_property
    def earliest_price_needed(self):
        if not self.activities.exists():
            return super().earliest_price_needed
        return self.activities.earliest().tradeDate

    @cached_property
    def latest_price_needed(self):
        if not self.activities.exists() or self.holdings.current().exists():
            return super().latest_price_needed
        return self.activities.latest().tradeDate

    @property
    def live_price_cad(self):
        return self.live_price * self.currency.live_price

    def GetPriceCAD(self, day):
        return self.GetRateOnDay(day) * self.currency.GetRateOnDay(day)


class StockSecurityManager(SecurityManager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.Stock)

    def SyncLive(self):
        for security in self.get_queryset().filter(holdings__enddate=None).distinct():
            security.SyncLiveAlphaVantagePrice()

    def Sync(self):
        for security in self.get_queryset():
            security.Sync()


class Stock(Security):
    objects = StockSecurityManager()

    class Meta:
        proxy = True

    @property
    def base_symbol(self):
        return self.symbol.split('.')[0]

    def Sync(self):
        self.SyncRates(self.GetAlphaVantageData)

    def SyncLiveAlphaVantagePrice(self):
        vals = self.GetAlphaVantageData(datetime.date.today(), datetime.date.today())
        try:
            if vals[0][1]:
                self.live_price = vals[0][1]
        except IndexError:
            pass

    def GetAlphaVantageData(self, start, end):
        # TODO: Monster hack for DLR - maybe have a fallback of some kind?
        if self.lookupSymbol == 'DLR.U.TO':
            index = pandas.date_range(start, end, freq='D').date
            return zip(index, pandas.Series(10.0, index))

        params = {'function': 'TIME_SERIES_DAILY',
                  'symbol': self.lookupSymbol, 'apikey': 'P38D2XH1GFHST85V'}
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


class CashSecurityManager(SecurityManager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.Cash)

    def Sync(self):
        for security in self.get_queryset():
            security.Sync()


class Cash(Security):
    objects = CashSecurityManager()

    class Meta:
        proxy = True

    def Sync(self):
        self.SyncRates(self._FakeData)
        self.currency.SyncExchangeRates()

        # TODO: hack for live USD exchange rates from OpenExchangeRates
        if self.currency.code == 'USD':
            self.currency.SyncLive()


class OptionSecurityManager(SecurityManager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.Option)

    def Create(self, callput, symbol, expiry, strike, currency_str):
        """
        callput is either 'call' or 'put'.
        symbol is the base symbol of the underlying
        expiry is a datetime.date
        strike is a Decimal
        currency_str is the 3 digit currency code
        """
        optsymbol = "{:<6}{}{}{:0>8}".format(symbol, expiry.strftime(
            '%y%m%d'), callput[0], Decimal(strike) * 1000)
        option, created = super().get_or_create(
            symbol=optsymbol,
            defaults={
                'description': "{} option for {}, strike {} expiring on {}.".format(callput.title(), symbol, strike,
                                                                                    expiry),
                'type': self.model.Type.Option,
                'currency_id': currency_str
            })
        return option

    def Sync(self):
        for security in self.get_queryset():
            security.Sync()


class Option(Security):
    objects = OptionSecurityManager()

    class Meta:
        proxy = True

    def GetOptionPrices(self, start, end):
        return self.activities.values_list('tradeDate', 'price').distinct('tradeDate')

    def Sync(self):
        self.SyncRates(self.GetOptionPrices)


class MutualFundSecurityManager(SecurityManager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.MutualFund)

    def Create(self, symbol, currency_str):
        return super().create(
            symbol=symbol,
            type=self.model.Type.MutualFund,
            currency_id=currency_str,
            lookupSymbol=symbol
        )

    def Sync(self):
        for security in self.get_queryset():
            security.Sync()


class MutualFund(Security):
    objects = MutualFundSecurityManager()

    class Meta:
        proxy = True

    def Sync(self):
        self.SyncPricesFromClient()
        self.SyncFromMorningStar()

    def SyncPricesFromClient(self):
        pass
        # TODO: Hacky mutual fund syncing, find a better way.
        # TODO: Dependency inject the syncer into the MutualFund
        # if self.GetShouldSyncRange()[1]:
        #     for c in BaseClient.objects.filter(accounts__activities__security=self).distinct():
        #         with c:
        #             c.SyncPrices()

    def SyncFromMorningStar(self):
        try:
            self.SyncRates(self.GetMorningstarData)
        except:
            pass

    def GetMorningstarData(self, start, end):
        RAW_URL = 'https://api.morningstar.com/service/mf/Price/Mstarid/{}?format=json&username=morningstar&password=ForDebug&startdate={}&enddate={}'
        url = RAW_URL.format(self.lookupSymbol, str(start), str(end))
        r = requests.get(url)
        json = r.json()
        if 'data' in json and 'Prices' in json['data']:
            return [(parser.parse(item['d']).date(), Decimal(item['v'])) for item in json['data']['Prices']]
        return []


class SecurityPriceQuerySet(models.query.QuerySet):
    def with_cad_prices(self):
        return self.filter(security__currency__rates__day=F('day')).annotate(
            exch=F('security__currency__rates__price'),
            cadprice=F('security__currency__rates__price') * F('price')
        )


class SecurityPrice(RateHistoryTableMixin):
    security = models.ForeignKey(Security, on_delete=models.CASCADE, related_name='rates')
    objects = SecurityPriceQuerySet.as_manager()

    class Meta:
        unique_together = ('security', 'day')
        get_latest_by = 'day'
        ordering = ['day']
        indexes = [
            models.Index(fields=['security']),
            models.Index(fields=['day'])
        ]

    def __str__(self):
        return "{} {} {}".format(self.security, self.day, self.price)


class SecurityPriceDetail(models.Model):
    security = models.ForeignKey(Security, on_delete=models.DO_NOTHING)
    day = models.DateField()
    price = models.DecimalField(max_digits=16, decimal_places=6)
    exch = models.DecimalField(max_digits=16, decimal_places=6)
    cad = models.DecimalField(max_digits=16, decimal_places=6)
    type = models.CharField(max_length=100)

    @classmethod
    def CreateView(cls):
        cursor = connection.cursor()
        try:
            cursor.execute("""DROP MATERIALIZED VIEW IF EXISTS securities_cadview;
CREATE MATERIALIZED VIEW public.securities_cadview
AS
 SELECT sec.day,
    sec.symbol as security_id,
    sec.price,
    er.price AS exch,
    sec.price * er.price AS cadprice,
    sec.type
   FROM ( SELECT s.symbol,
            s.currency_id,
            sp.day,
            sp.price,
            s.type
           FROM securities_security s
             JOIN securities_securityprice sp ON s.symbol::text = sp.security_id::text) sec
     JOIN securities_exchangerate er ON sec.day = er.day AND sec.currency_id::text = er.currency_id::text
WITH DATA;
ALTER TABLE securities_cadview OWNER TO financeuser;
""")
            connection.commit()
        finally:
            cursor.close()

    @classmethod
    def Refresh(cls):
        cursor = connection.cursor()
        try:
            cursor.execute("REFRESH MATERIALIZED VIEW securities_cadview;")
            connection.commit()
        finally:
            cursor.close()

    class Meta:
        managed = False
        db_table = 'securities_cadview'
        get_latest_by = 'day'
        ordering = ['day']

    def __str__(self):
        return '{} {} {:.2f} {:.2f} {:.4f} {}'.format(
            self.security_id, self.day,
            self.price, self.exch, self.cad, self.type)

    def __repr__(self):
        return '{} {} {:.2f} {:.2f} {:.4f} {}'.format(
            self.security_id, self.day,
            self.price, self.exch, self.cad, self.type)
