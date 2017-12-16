import datetime
from decimal import Decimal

from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction, connection
from django.utils.functional import cached_property

from datasource.models import DataSourceMixin, ConstantDataSource, PandasDataSource, AlphaVantageDataSource, \
    MorningstarDataSource, StartEndDataSource

import requests
from model_utils import Choices


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
        except RateHistoryTableMixin.DoesNotExist:
            return self.rates.latest().price

    @live_price.setter
    def live_price(self, value):
        self.rates.update_or_create(day=datetime.date.today(), defaults={'price': value})

    def SyncRates(self):
        start, end = self.GetShouldSyncRange()
        if start is None:
            return []

        data = self.datasource.GetData(start, end)

        with transaction.atomic():
            for day, price in data:
                self.rates.update_or_create(day=day, defaults={'price': price})


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

        ((start_day, start_val), (end_day, end_val),) = option.activities.values_list(
            'tradeDate', 'price').distinct('tradeDate')
        datasource, _ = StartEndDataSource.objects.get_or_create(
            start_day=start_day,
            start_val=start_val,
            end_day=end_day,
            end_val=end_val)
        option.update(datasource=datasource)
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
            currency_id=currency_str,
            datasource=datasource
        )

class Security(RateLookupMixin):
    Type = Choices('Stock', 'Option', 'Cash', 'MutualFund')
    symbol = models.CharField(max_length=32, primary_key=True)
    description = models.CharField(max_length=500, null=True, blank=True, default='')
    type = models.CharField(max_length=12, choices=Type, default=Type.Stock)
    currency_id = models.CharField(max_length=3, default='XXX')

    objects = SecurityManager()
    stocks = StockSecurityManager()
    options = OptionSecurityManager()
    cash = CashSecurityManager()
    mutualfunds = MutualFundSecurityManager()

    def __str__(self):
        return "{} {}".format(self.symbol, self.currency_id)

    def __repr(self):
        return "Security({} ({}) {})".format(self.symbol, self.currency_id, self.description)

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

    def GetTodaysChange(self):
        rates = self.rates.filter(
            day__gte=datetime.date.today() - datetime.timedelta(days=1)
        ).values_list('price', flat=True)
        yesterday = 1 / rates[0]
        today = 1 / rates[1]
        return today, (today - yesterday) / yesterday


class SecurityPriceQuerySet(models.query.QuerySet):
    def today(self):
        return self.filter(day=datetime.date.today())

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
SELECT p.symbol as security_id, 
    p.day, 
    p.price, 
    c.price as exch,
    p.price * c.price as cadprice,
    p.type    
    FROM (SELECT sec.symbol, 
     sec.currency_id||' Cash' as cashhack, 
     pr.day, 
     pr.price,
     sec.type 
     FROM securities_security sec 
        JOIN securities_securityprice pr ON sec.symbol=pr.security_id) p 
        LEFT JOIN securities_securityprice c on p.day=c.day and c.security_id=p.cashhack
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
