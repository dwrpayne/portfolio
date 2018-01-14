import datetime
from decimal import Decimal

from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction, connection
from django.utils.functional import cached_property
from model_utils import Choices

from datasource.models import DataSourceMixin, ConstantDataSource, PandasDataSource, AlphaVantageDataSource, \
    MorningstarDataSource, InterpolatedDataSource
from datasource.services import GetLiveAlphaVantageExchangeRate, GetYahooStockData
from utils.db import SecurityMixinQuerySet, DayMixinQuerySet


class SecurityQuerySet(models.QuerySet):
    def create(self, **kwargs):
        kwargs.setdefault('type', self.model.Type.Stock if len(kwargs['symbol']) < 20 else self.model.Type.Option)
        kwargs.setdefault('datasource', self.model.get_default_datasource(kwargs['type'], kwargs['symbol']))
        if kwargs['type'] == self.model.Type.Stock:
            pass#kwargs['metadata'] = GetYahooStockData(kwargs['symbol'])
        return super().create(**kwargs)


class SecurityManager(models.Manager):
    def Sync(self, live_update):
        queryset = self.get_queryset()
        if live_update:
            queryset = queryset.filter(holdings__enddate__isnull=True).distinct()
        for security in queryset:
            security.SyncRates(live_update)
            if live_update and security.type==self.model.Type.Cash and not security.symbol == 'CAD':
                security.live_price = GetLiveAlphaVantageExchangeRate(security.symbol)


class StockSecurityManager(SecurityManager):
    def get_queryset(self):
        return super().get_queryset().filter(type=self.model.Type.Stock)

    def create(self, **kwargs):
        kwargs['type'] = self.model.Type.Stock
        return super().create(**kwargs)


class CashSecurityManager(SecurityManager):
    def get_queryset(self):
        return super().get_queryset().filter(type=self.model.Type.Cash)

    def create(self, **kwargs):
        kwargs['type'] = self.model.Type.Cash
        return super().create(**kwargs)


class MutualFundSecurityManager(SecurityManager):
    def get_queryset(self):
        return super().get_queryset().filter(type=self.model.Type.MutualFund)

    def create(self, **kwargs):
        kwargs['type'] = self.model.Type.MutualFund
        return super().create(**kwargs)


class OptionSecurityManager(SecurityManager):
    def get_queryset(self):
        return super().get_queryset().filter(type__in=[self.model.Type.Option, self.model.Type.OptionMini])

    def UpdateDataSources(self):
        for option in self.get_queryset():
            start, *_, end = option.activities.values_list('tradeDate', 'price')
            datasource, created = InterpolatedDataSource.objects.get_or_create(start_day=start[0],
                                                                      start_val=start[1],
                                                                      end_day=end[0],
                                                                      end_val=end[1])
            option.SetDataSource(datasource)

    def CreateFromDetails(self, callput, symbol, expiry, strike, currency_str):
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
        option, _ = super().get_or_create(
            symbol=optsymbol,
            defaults={
                'description': "{} option for {}, strike {} expiring on {}.".format(callput.title(), symbol, strike,
                                                                                    expiry),
                'type': type,
                'currency': currency_str
            })

        return option


class Security(models.Model):
    Type = Choices('Stock', 'Option', 'OptionMini', 'Cash', 'MutualFund')
    symbol = models.CharField(max_length=32, primary_key=True)
    description = models.CharField(max_length=500, null=True, blank=True, default='')
    type = models.CharField(max_length=12, choices=Type, default=Type.Stock)
    currency = models.CharField(max_length=3, default='XXX')
    datasource = models.ForeignKey(DataSourceMixin, null=True, blank=True,
                                   default=None, on_delete=models.DO_NOTHING)

    objects = SecurityManager.from_queryset(SecurityQuerySet)()
    stocks = StockSecurityManager.from_queryset(SecurityQuerySet)()
    options = OptionSecurityManager.from_queryset(SecurityQuerySet)()
    cash = CashSecurityManager.from_queryset(SecurityQuerySet)()
    mutualfunds = MutualFundSecurityManager().from_queryset(SecurityQuerySet)()

    def __str__(self):
        return "{}".format(self.symbol)

    def __repr(self):
        return "Security({} ({}) {})".format(self.symbol, self.currency, self.description)

    class Meta:
        verbose_name_plural = 'Securities'
        indexes = [
            models.Index(fields=['symbol']),
            models.Index(fields=['currency'])
        ]

    def __lt__(self, other):
        if self.type > other.type:
            return True
        return self.symbol < other.symbol

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

    @classmethod
    def get_default_datasource(cls, type, symbol):
        obj = None
        if type == cls.Type.Stock:
            obj, created = AlphaVantageDataSource.objects.get_or_create(symbol=symbol)
        if type == cls.Type.Cash:
            obj = PandasDataSource.objects.create_bankofcanada(currency_code=symbol)
        if type == cls.Type.MutualFund:
            obj, created = MorningstarDataSource.objects.get_or_create(symbol=symbol)
        return obj

    def SetDataSource(self, datasource):
        self.datasource = datasource
        self.save()

    def RefreshMetadata(self):
        if self.type == self.Type.Stock:
            self.metadata = GetYahooStockData(self.symbol)

    def NeedsSync(self):
        return self.GetShouldSyncRange(False)[0] is not None

    def GetShouldSyncRange(self, force_today):
        """ Returns a pair (start,end) of datetime.dates that need to be synced."""
        try:
            earliest = self.prices.earliest().day
            latest = self.prices.latest().day
        except ObjectDoesNotExist:
            return self.earliest_price_needed, self.latest_price_needed

        if earliest > self.earliest_price_needed:
            return self.earliest_price_needed - datetime.timedelta(days=7), self.latest_price_needed

        if latest < self.latest_price_needed or force_today:
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

    def SyncRates(self, force_today=False):
        start, end = self.GetShouldSyncRange(force_today)
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

class Option(Security):
    class Meta:
        proxy = True

    @cached_property
    def underlying(self):
        return self.symbol[:6].strip()

    @cached_property
    def expiry(self):
        return datetime.datetime.strptime(self.symbol[6:12], '%y%m%d')

    @cached_property
    def is_call(self):
        return self.symbol[12].lower() == 'c'

    @cached_property
    def is_put(self):
        return self.symbol[12].lower() == 'p'

    @cached_property
    def strike(self):
        return float(self.symbol[13:]) / 1000


class SecurityPriceQuerySet(models.query.QuerySet,
                            SecurityMixinQuerySet,
                            DayMixinQuerySet):
    pass


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
    security = models.ForeignKey(Security, on_delete=models.DO_NOTHING, related_name='pricedetails')
    day = models.DateField()
    price = models.DecimalField(max_digits=16, decimal_places=6)
    exch = models.DecimalField(max_digits=16, decimal_places=6)
    cadprice = models.DecimalField(max_digits=16, decimal_places=6)
    type = models.CharField(max_length=100)

    objects = SecurityPriceQuerySet.as_manager()

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
