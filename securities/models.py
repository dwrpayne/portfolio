import datetime
from decimal import Decimal

from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction, connection
from django.utils.functional import cached_property

from datasource.models import DataSourceMixin, ConstantDataSource, PandasDataSource, AlphaVantageDataSource, \
    MorningstarDataSource, StartEndDataSource

import requests
from model_utils import Choices


class SecurityManager(models.Manager):
    def Create(self, symbol, currency):
        if len(symbol) >= 20:
            return self.CreateOptionRaw(symbol, currency)
        else:
            return self.CreateStock(symbol, currency)

    def CreateStock(self, symbol, currency):
        return self.create(
            symbol=symbol,
            type=self.model.Type.Stock,
            currency=currency
        )

    def CreateOptionRaw(self, optsymbol, currency):
        return self.create(
            symbol=optsymbol,
            type=self.model.Type.Option,
            currency=currency
        )

    def Sync(self):
        for security in self.get_queryset():
            security.SyncRates()

            #TODO USD live sync hack
            if security.symbol == 'USD':
                request = requests.get('https://openexchangerates.org/api/latest.json',
                                       params={'app_id': '2f666e800586440088f5fc22d688f520', 'symbols': 'CAD'})
                security.live_price = Decimal(str(request.json()['rates']['CAD']))


class StockSecurityManager(SecurityManager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.Stock)

    def create(self, *args, **kwargs):
        if not 'datasource' in kwargs:
            kwargs['datasource'], _ = AlphaVantageDataSource.objects.get_or_create(symbol=kwargs['symbol'])
        super().create(*args, **kwargs)

        def DefaultInit(self):
            self.create(symbol='CAD')
            self.create(symbol='USD')


class CashSecurityManager(SecurityManager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.Cash)

    def create(self, *args, **kwargs):
        if not 'datasource' in kwargs:
            if kwargs['symbol'] == 'CAD':
                datasource, _ = ConstantDataSource.objects.get_or_create()
            else:
                datasource, _ = PandasDataSource.objects.get_or_create(
                    symbol='FXCADUSD', source='bankofcanada', column='FXCADUSD')
            kwargs['datasource'] = datasource

        cash = super().create(*args, **kwargs)
        return cash


class OptionSecurityManager(SecurityManager):
    def get_queryset(self):
        return super().get_queryset().filter(type__in=[Security.Type.Option, Security.Type.OptionMini])

    def Create(self, callput, symbol, expiry, strike, currency_str):
        """
        callput is either 'call' or 'put'.
        symbol is the base symbol of the underlying
        expiry is a datetime.date
        strike is a Decimal
        currency_str is the 3 digit currency code
        """
        type = self.model.Type.Option
        if '7' in symbol:
            symbol = symbol.strip('7')
            type = self.model.Type.OptionMini
        optsymbol = "{:<6}{}{}{:0>8}".format(symbol, expiry.strftime(
            '%y%m%d'), callput[0], Decimal(strike) * 1000)
        option, created = super().get_or_create(
            symbol=optsymbol,
            defaults={
                'description': "{} option for {}, strike {} expiring on {}.".format(callput.title(), symbol, strike,
                                                                                    expiry),
                'type': type,
                'currency': currency_str
            })

        return option


class MutualFundSecurityManager(SecurityManager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.MutualFund)

    def Create(self, symbol, currency_str, datasource=None):
        if not datasource:
            datasource, _ = MorningstarDataSource.objects.get_or_create(symbol=symbol)
        return super().create(
            symbol=symbol,
            type=self.model.Type.MutualFund,
            currency=currency_str,
            datasource=datasource
        )

class Security(models.Model):
    Type = Choices('Stock', 'Option', 'OptionMini', 'Cash', 'MutualFund')
    symbol = models.CharField(max_length=32, primary_key=True)
    description = models.CharField(max_length=500, null=True, blank=True, default='')
    type = models.CharField(max_length=12, choices=Type, default=Type.Stock)
    currency = models.CharField(max_length=3, default='XXX')
    datasource = models.ForeignKey(DataSourceMixin, null=True, blank=True,
                                   default=None, on_delete=models.DO_NOTHING)

    objects = SecurityManager()
    stocks = StockSecurityManager()
    options = OptionSecurityManager()
    cash = CashSecurityManager()
    mutualfunds = MutualFundSecurityManager()

    def __str__(self):
        return "{} {}".format(self.symbol, self.currency)

    def __repr(self):
        return "Security({} ({}) {})".format(self.symbol, self.currency, self.description)

    class Meta:
        verbose_name_plural = 'Securities'
        indexes = [
            models.Index(fields=['symbol']),
            models.Index(fields=['currency'])
        ]

    @cached_property
    def earliest_price_needed(self):
        if not self.activities.exists():
            return datetime.date.today()
        return self.activities.earliest().tradeDate

    @cached_property
    def latest_price_needed(self):
        if not self.activities.exists() or self.holdings.current().exists():
            return datetime.date.today()
        return self.activities.latest().tradeDate

    @cached_property
    def price_multiplier(self):
        if self.type == self.Type.Option:
            return 100
        if self.type == self.Type.OptionMini:
            return 10

    def GetShouldSyncRange(self):
        """ Returns a pair (start,end) of datetime.dates that need to be synced."""
        try:
            earliest = self.prices.earliest().day
            latest = self.prices.latest().day
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
            return self.prices.get(day=datetime.date.today()).price
        except SecurityPrice.DoesNotExist:
            return self.prices.latest().price

    @live_price.setter
    def live_price(self, value):
        self.prices.update_or_create(day=datetime.date.today(), defaults={'price': value})

    @property
    def yesterday_price(self):
        try:
            return self.prices.get(day=datetime.date.today() - datetime.timedelta(days=1)).price
        except SecurityPrice.DoesNotExist:
            return 0

    def SyncRates(self):
        start, end = self.GetShouldSyncRange()
        if start is None:
            return []

        data = self.datasource.GetData(start, end)

        with transaction.atomic():
            for day, price in data:
                self.prices.update_or_create(day=day, defaults={'price': price})

    def GetTodaysChange(self):
        rates = self.prices.filter(
            day__gte=datetime.date.today() - datetime.timedelta(days=1)
        ).values_list('price', flat=True)
        yesterday = 1 / rates[0]
        today = 1 / rates[1]
        return today, (today - yesterday) / yesterday


class SecurityPriceQuerySet(models.query.QuerySet):
    def today(self):
        return self.filter(day=datetime.date.today())


class SecurityPrice(models.Model):
    security = models.ForeignKey(Security, on_delete=models.CASCADE, related_name='prices')
    day = models.DateField(default=datetime.date.today)
    price = models.DecimalField(max_digits=19, decimal_places=6)

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
    cadprice = models.DecimalField(max_digits=16, decimal_places=6)
    type = models.CharField(max_length=100)

    @classmethod
    def CreateView(cls, drop_cascading=False):
        cursor = connection.cursor()
        try:
            cursor.execute("DROP MATERIALIZED VIEW IF EXISTS securities_cadview {};".format("CASCADE" if drop_cascading else ""))
            cursor.execute("""
CREATE MATERIALIZED VIEW public.securities_cadview
AS
SELECT prices.symbol as security_id, 
    prices.day, 
    prices.price,
    COALESCE(currencies.price, 1) as exch,
    prices.price * COALESCE(currencies.price, 1) as cadprice,
    prices.type,    
    row_number() OVER () AS id
    FROM (SELECT s.symbol, 
     s.currency, 
     p.day, 
     p.price,
     s.type 
     FROM securities_security s 
        JOIN securities_securityprice p ON s.symbol=p.security_id) prices
        LEFT JOIN securities_securityprice currencies on prices.day=currencies.day and currencies.security_id=prices.currency
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
            self.price, self.exch, self.cadprice, self.type)

    def __repr__(self):
        return '{} {} {:.2f} {:.2f} {:.4f} {}'.format(
            self.security_id, self.day,
            self.price, self.exch, self.cadprice, self.type)