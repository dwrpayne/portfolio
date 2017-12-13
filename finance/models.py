from django.db import models, transaction, connection
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import F, Q, Sum, Case, When
from django.db.models.expressions import RawSQL
from django.utils.functional import cached_property
from django.conf import settings
from polymorphic.models import PolymorphicModel
from polymorphic.query import PolymorphicQuerySet
from polymorphic.manager import PolymorphicManager

from collections import defaultdict
from decimal import Decimal
import datetime
from model_utils import Choices
import arrow
import utils.dates
from utils.misc import plotly_iframe_from_url
import pandas
from dateutil import parser
import requests
from pandas_datareader import data as pdr


class RateHistoryTableMixin(models.Model):
    """
    A mixin class for rate history.
    Classes that use this must define a foreign key back to the related RateLookupMixin with related_name="rates"
    """
    day = models.DateField(default=datetime.date.today)
    price = models.DecimalField(max_digits=19, decimal_places=6)

    class Meta:
        abstract = True


class RateLookupMixin(models.Model):
    """
    A mixin class that adds the necessary fields to support looking up historical rates from pandas-datareader
    Classes that use this must define a subclass of RateHistoryTableMixin and create a foreign key back to this class with related_name="rates"
    """
    lookupSymbol = models.CharField(max_length=32, null=True, blank=True, default=None)
    lookupSource = models.CharField(max_length=32, null=True, blank=True, default=None)
    lookupColumn = models.CharField(max_length=32, null=True, blank=True, default=None)

    @property
    def earliest_price_needed(self):
        return datetime.date(2009, 1, 1)

    @property
    def latest_price_needed(self):
        return datetime.date.today()

    def GetShouldSyncRange(self):
        """ Returns a pair (start,end) of datetime.dates that need to be synced."""
        earliest = None
        latest = None
        try:
            earliest = self.rates.earliest().day
            latest = self.rates.latest().day
        except ObjectDoesNotExist:
            return (self.earliest_price_needed, self.latest_price_needed)

        if earliest > self.earliest_price_needed:
            return (self.earliest_price_needed - datetime.timedelta(days=7), self.latest_price_needed)

        if latest < self.latest_price_needed:
            return (latest - datetime.timedelta(days=7), self.latest_price_needed)

        return (None, None)

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
        It gets passed (lookup, start, end) and is expected to return an iterator of (day, price) pairs or a pandas dataframe
        """
        start, end = self.GetShouldSyncRange()
        if start is None:
            print('Already synced data for {}, skipping.'.format(self.lookupSymbol))
            return []

        data = self._ProcessRateData(retriever_fn(self, start, end), end)

        with transaction.atomic():
            for day, price in data:
                self.rates.update_or_create(day=day, defaults={'price': price})

    def GetRateOnDay(self, day):
        return self.rates.get(day=day).price

    class Meta:
        abstract = True


class Currency(RateLookupMixin):
    code = models.CharField(max_length=3, primary_key=True)

    def __str__(self):
        return self.code

    class Meta:
        verbose_name_plural = 'Currencies'
        
    def GetTodaysChange(self):
        rates = self.rates.filter(
            day__gte=datetime.date.today()-datetime.timedelta(days=1)
            ).values_list('price', flat=True)
        yesterday = 1/rates[0]
        today = 1/rates[1]
        return (today, (today-yesterday)/yesterday)        
                

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
    def create(self, symbol, currency, **kwargs):
        if len(symbol) >= 20:
            security = self.CreateOptionRaw(symbol, currency)
        else:
            security = self.CreateStock(symbol, currency)

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

def Stock(Security):
    objects = StockSecurityManager()
    class Meta:
        proxy = True        

class CashSecurityManager(SecurityManager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.Cash)
    
def Cash(Security):
    objects = CashSecurityManager()
    class Meta:
        proxy = True

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
                'description': "{} option for {}, strike {} expiring on {}.".format(callput.title(), symbol, strike, expiry),
                'type': self.model.Type.Option,
                'currency_id': currency_str
            })
        return option

def Option(Security):
    objects = OptionSecurityManager()
    class Meta:
        proxy = True

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

def MutualFund(Security):
    objects = MutualFundSecurityManager()
    class Meta:
        proxy = True


class SecurityPriceQuerySet(models.query.QuerySet):
    def with_cad_prices(self):
        return self.filter(security__currency__rates__day=F('day')).annotate(
            exch=F('security__currency__rates__price'),
            cadprice=F('security__currency__rates__price')*F('price')
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
    

class DataProvider:
    @classmethod
    def _FakeData(cls, lookup, start, end):
        for day in pandas.date_range(start, end).date:
            yield day, 1.

    @classmethod
    def _RetrievePandasData(cls, lookup, start, end):
        """ Returns a list of tuples (day, price) """
        FAKED_VALS = {'DLR.U.TO': 10.}
        if lookup.lookupSymbol in FAKED_VALS:
            index = pandas.date_range(start, end, freq='D').date
            return zip(index, pandas.Series(cls.FAKED_VALS[lookup.lookupSymbol], index))

        print('Syncing prices for {} from {} to {}...'.format(lookup.lookupSymbol, start, end))
        for retry in range(5):
            try:
                return pdr.DataReader(lookup.lookupSymbol, lookup.lookupSource, start, end)
            except:
                pass
        return []

    @classmethod
    def GetAlphaVantageData(cls, lookup, start, end):
        fake = {'DLR.U.TO': 10., 'CAD': 1.}
        if lookup.lookupSymbol in fake:
            index = pandas.date_range(start, end, freq='D').date
            return zip(index, pandas.Series(fake[lookup.lookupSymbol], index))

        print('Syncing prices for {} from {} to {}...'.format(lookup.lookupSymbol, start, end))
        params = {'function': 'TIME_SERIES_DAILY',
                  'symbol': lookup.lookupSymbol, 'apikey': 'P38D2XH1GFHST85V'}
        if (end - start).days > 100:
            params['outputsize'] = 'full'
        r = requests.get('https://www.alphavantage.co/query', params=params)
        json = r.json()
        if 'Time Series (Daily)' in json:
            return [(parser.parse(day).date(), Decimal(vals['4. close'])) for day, vals in json['Time Series (Daily)'].items() if str(start) <= day <= str(end)]
        return []

    @classmethod
    def GetMorningstarData(cls, lookup, start, end):
        RAW_URL = 'https://api.morningstar.com/service/mf/Price/Mstarid/{}?format=json&username=morningstar&password=ForDebug&startdate={}&enddate={}'
        url = RAW_URL.format(lookup.lookupSymbol, str(start), str(end))
        print('Syncing prices for {} from {} to {}...'.format(lookup.lookupSymbol, start, end))
        r = requests.get(url)
        json = r.json()
        if 'data' in json and 'Prices' in json['data']:
            return [(parser.parse(item['d']).date(), Decimal(item['v'])) for item in json['data']['Prices']]
        return []

    @classmethod
    def GetLiveStockPrice(cls, symbol):
        symbol = symbol.split('.')[0]
        params = {'function': 'TIME_SERIES_INTRADAY', 'symbol': symbol,
                  'apikey': 'P38D2XH1GFHST85V', 'interval': '1min'}
        r = requests.get('https://www.alphavantage.co/query', params=params)
        json = r.json()
        price = Decimal(0)
        if 'Time Series (1min)' in json:
            newest = json["Meta Data"]["3. Last Refreshed"]
            price = Decimal(json['Time Series (1min)'][newest]['4. close'])
        else:
            print(symbol, json)
            print(r, r.content)
        print('Getting live price for {}... {}'.format(symbol, price))
        return price

    @classmethod
    def SyncLiveSecurities(cls):
        for security in Stock.objects.filter(holdings__isnull=False, holdings__enddate=None).distinct():
            price = cls.GetLiveStockPrice(security.symbol)
            if price:
                security.live_price = price

        for fund in MutualFund.objects.all():
            if fund.GetShouldSyncRange()[1]:
                for c in BaseClient.objects.filter(accounts__activities__security=fund).distinct():
                    with c:
                        c.SyncPrices()

        # Just generate fake 1 entries so we can join these tables later.
        for cash in Cash.objects.all():
            cash.SyncRates(cls._FakeData)

    @classmethod
    def SyncAllSecurities(cls):
        for stock in Stock.objects.all():
            stock.SyncRates(cls.GetAlphaVantageData)

        for option in Option.objects.all():
            option.SyncRates(lambda l, s, e: option.activities.values_list(
                'tradeDate', 'price').distinct('tradeDate'))

        for fund in MutualFund.objects.all():
            try:
                fund.SyncRates(cls.GetMorningstarData)
            except:
                pass
            if fund.GetShouldSyncRange()[1]:
                for c in BaseClient.objects.filter(accounts__activities__security=fund).distinct():
                    with c:
                        c.SyncPrices()

        # Just generate fake 1 entries so we can join these tables later.
        for cash in Cash.objects.all():
            cash.SyncRates(cls._FakeData)

    @classmethod
    def SyncAllExchangeRates(cls):
        for currency in Currency.objects.all():
            Security.objects.get_or_create(
                symbol=currency.code + ' Cash', currency=currency, type=Security.Type.Cash)
            currency.SyncRates(cls._FakeData if currency.code == 'CAD' else cls._RetrievePandasData)

        r = requests.get('https://openexchangerates.org/api/latest.json',
                         params={'app_id': '2f666e800586440088f5fc22d688f520', 'symbols': 'CAD'})
        Currency.objects.get(code='USD').live_price = Decimal(str(r.json()['rates']['CAD']))


class BaseClient(PolymorphicModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE, related_name='clients')
    display_name = models.CharField(max_length=100, null=True)

    @property
    def activitySyncDateRange(self):
        return 30

    def __str__(self):
        return "{}".format(self.display_name)

    def __repr__(self):
        return 'BaseClient<{}>'.format(self.display_name)

    def __enter__(self):
        self.Authorize()
        return self

    def __exit__(self, type, value, traceback):
        self.CloseSession()

    def Authorize(self):
        pass

    def CloseSession(self):
        pass

    @property
    def currentSecurities(self):
        return Security.objects.filter(holdings__account__client=self, holdings__enddate=None).distinct()

    def _CreateRawActivities(self, account, start, end):
        """ 
        Retrieve raw activity data from your client source for the specified account and start/end period.
        Store it in the DB as a subclass of BaseRawActivity.
        Return the number of new raw activities created.
        """
        return 0

    def SyncAccounts(self):
        pass

    def SyncActivities(self, account):
        """
        Syncs all raw activities for the specified account from data source.
        Returns the number of new raw activities created.
        """
        start = account.GetMostRecentActivityDate()
        if start:
            start = arrow.get(start).shift(days=+1)
        else:
            start = arrow.get('2011-02-01')

        date_range = arrow.Arrow.interval('day', start, arrow.now(), self.activitySyncDateRange)

        print('Syncing all activities for {} in {} chunks.'.format(account, len(date_range)))
        return sum(self._CreateRawActivities(account, start, end) for start, end in date_range)

    def Refresh(self):
        self.SyncAccounts()
        for account in self.accounts.all():
            new_activities = self.SyncActivities(account)
            # TODO: Better error handling when we can't actually sync new activities from server. Should we still regen here?
            if new_activities >= 0:
                account.RegenerateActivities()
                account.RegenerateHoldings()

    def SyncPrices(self):
        pass

    def SyncCurrentAccountBalances(self):
        pass


class BaseAccountQuerySet(PolymorphicQuerySet):
    def for_user(self, user):
        return self.filter(client__user=user)

    def get_balance_totals(self):
        properties = ['cur_balance', 'cur_cash_balance', 'yesterday_balance', 'today_balance_change']
        return {p : sum(getattr(a, p) for a in self) for p in properties}


class BaseAccount(PolymorphicModel):
    client = models.ForeignKey(BaseClient, on_delete=models.CASCADE, related_name='accounts')
    type = models.CharField(max_length=100)
    id = models.CharField(max_length=100, primary_key=True)
    taxable = models.BooleanField(default=True)
    display_name = models.CharField(max_length=100, editable=False, default='')

    objects = PolymorphicManager.from_queryset(BaseAccountQuerySet)()

    class Meta:
        ordering = ['id']

    def __repr__(self):
        return "BaseAccount({},{},{})".format(self.client, self.id, self.type)

    def __str__(self):
        return "{} {} {}".format(self.client, self.id, self.type)

    def save(self, *args, **kwargs):
        self.display_name = "{} {}".format(self.client, self.type)
        super().save(*args, **kwargs)

    @property
    def cur_cash_balance(self):
        query = self.holdingdetail_set.cash().today().total_values()
        if query:
            return query.first()[1]
        return 0

    @property
    def cur_balance(self):
        return self.GetValueToday()

    @property
    def yesterday_balance(self):
        return self.GetValueAtDate(datetime.date.today() - datetime.timedelta(days=1))

    @property
    def today_balance_change(self):
        return self.cur_balance - self.yesterday_balance


    def RegenerateActivities(self):
        self.activities.all().delete()
        Activity.objects.GenerateFromRaw(self.rawactivities.all())

    def RegenerateHoldings(self):
        self.holding_set.all().delete()
        self.HackInit()
        for activity in self.activities.all():
            for security, qty_delta in activity.GetHoldingEffect().items():
                self.holding_set.add_effect(self, security, qty_delta, activity.tradeDate)
        self.holding_set.filter(qty=0).delete()

    def HackInit(self):
        pass

    def GetMostRecentActivityDate(self):
        try:
            return self.activities.latest().tradeDate
        except:
            return None

    def GetValueAtDate(self, date):
        return self.holdingdetail_set.at_date(date).total_values().first()[1]

    def GetValueToday(self):
        return self.holdingdetail_set.today().total_values().first()[1]

    def GetDividendsInYear(self, year):
        sum(self.activities.dividends().in_year(year).values_list('netAmount', flat=True))


class HoldingManager(models.Manager):
    def add_effect(self, account, security, qty_delta, date):
        previous_qty = 0
        try:
            current_holding = self.get(security=security, enddate=None)
            if current_holding.startdate == date:
                current_holding.AddQty(qty_delta)
                return
            else:
                current_holding.SetEndsOn(date - datetime.timedelta(days=1))
                previous_qty = current_holding.qty

        except Holding.MultipleObjectsReturned:
            print("HoldingManager.add_effect() returned multiple holdings for query {} {} {}".format(security))
        except Holding.DoesNotExist:
            pass

        new_qty = previous_qty + qty_delta
        if new_qty:
            print("Creating {} {} {} {}".format(security, new_qty, date, None))
            self.create(account=account, security=security,
                        qty=new_qty, startdate=date, enddate=None)
            

class HoldingQuerySet(models.query.QuerySet):
    def current(self):
        return self.filter(enddate=None)

    def for_user(self, user):
        return self.filter(account__client__user=user)
        

class Holding(models.Model):
    account = models.ForeignKey(BaseAccount, on_delete=models.CASCADE)
    security = models.ForeignKey(Security, on_delete=models.CASCADE, related_name='holdings')
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    startdate = models.DateField()
    enddate = models.DateField(null=True)

    objects = HoldingManager.from_queryset(HoldingQuerySet)()
    objects.use_for_related_fields = True

    class Meta:
        unique_together = ('account', 'security', 'startdate')
        get_latest_by = 'startdate'
        indexes = [
            models.Index(fields=['security_id', 'startdate', 'enddate']),
            models.Index(fields=['startdate']),
            models.Index(fields=['enddate']),
        ]

    def __str__(self):
        return "{} {} {}, {} - {}".format(self.account, self.qty, self.security, self.startdate, self.enddate)

    def __repr__(self):
        return "Holding({},{},{},{},{})".format(self.account, self.security, self.qty, self.startdate, self.enddate)

    def AddQty(self, qty_delta):
        self.qty += qty_delta
        if self.qty == 0:
            self.delete()
        else:
            self.save()

    def SetEndsOn(self, date):        
        self.enddate = date
        self.save(update_fields=['enddate'])


class BaseRawActivity(PolymorphicModel):
    account = models.ForeignKey(BaseAccount, on_delete=models.CASCADE, related_name='rawactivities')

    def CreateActivity(self):
        pass


class ManualRawActivity(BaseRawActivity):
    day = models.DateField()
    security = models.CharField(max_length=100)
    description = models.CharField(max_length=1000)
    cash = models.CharField(max_length=100)
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    netAmount = models.DecimalField(max_digits=16, decimal_places=2)
    type = models.CharField(max_length=100)

    class Meta:
        verbose_name_plural = 'Base Raw Activities'

    def CreateActivity(self):
        security = None
        if self.security:
            try:
                security = Security.objects.get(symbol=self.security)
            except Security.DoesNotExist:
                security = Security.objects.create(self.security, self.cash)

        Activity.objects.create(account=self.account, tradeDate=self.day, security=security, 
                    description=self.description, cash_id=self.cash + ' Cash', qty=self.qty,
                    price=self.price, netAmount=self.netAmount, type=self.type, raw=self)
    
class ActivityManager(models.Manager):
    def create(self, *args, **kwargs):
        if 'cash_id' in kwargs and not kwargs['cash_id']:
            kwargs['cash_id'] = None
        super().create(*args, **kwargs)

    def GenerateFromRaw(self, rawactivities):
        with transaction.atomic():
            for raw in rawactivities: 
                raw.CreateActivity()

class ActivityQuerySet(models.query.QuerySet):
    def in_year(self, year):
        return self.filter(tradeDate__year=year)

    def for_user(self, user):
        return self.filter(account__client__user=user)

    def deposits(self):
        return self.filter(type=Activity.Type.Deposit)
    
    def dividends(self):
        return self.filter(type=Activity.Type.Dividend)


class Activity(models.Model):
    account = models.ForeignKey(BaseAccount, on_delete=models.CASCADE, related_name='activities')
    tradeDate = models.DateField()
    security = models.ForeignKey(Security, on_delete=models.CASCADE,
                                 null=True, related_name='activities')
    description = models.CharField(max_length=1000)
    cash = models.ForeignKey(Security, on_delete=models.CASCADE,
                             null=True, related_name='dontaccess_cash')
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    netAmount = models.DecimalField(max_digits=16, decimal_places=2)
    Type = Choices('Deposit', 'Dividend', 'FX', 'Fee', 'Interest', 'Buy', 'Sell',
                   'Transfer', 'Withdrawal', 'Expiry', 'Journal', 'NotImplemented')
    type = models.CharField(max_length=100, choices=Type)
    raw = models.ForeignKey(BaseRawActivity, on_delete=models.CASCADE)

    
    objects = ActivityManager.from_queryset(ActivityQuerySet)()
    objects.use_for_related_fields = True

    class Meta:
        unique_together = ('account', 'tradeDate', 'security', 'cash', 'qty',
                           'price', 'netAmount', 'type', 'description')
        verbose_name_plural = 'Activities'
        get_latest_by = 'tradeDate'
        ordering = ['tradeDate']

    def __str__(self):
        return "{} - {} - {}\t{}\t{}\t{}\t{}".format(self.account, self.tradeDate, self.security, self.qty, self.price, self.type, self.description)

    def __repr__(self):
        return "Activity({},{},{},{},{},{},{},{})".format(self.tradeDate, self.security, self.cash, self.qty, self.price, self.netAmount, self.type, self.description)

    def GetHoldingEffect(self):
        """Generates a dict {security:amount, ...}"""
        effect = defaultdict(Decimal)

        if self.type in [Activity.Type.Buy, Activity.Type.Sell, Activity.Type.Deposit, Activity.Type.Withdrawal]:
            effect[self.security] = self.qty
            if self.cash:
                effect[self.cash] = self.netAmount

        elif self.type in [Activity.Type.Transfer, Activity.Type.Dividend, Activity.Type.Fee, Activity.Type.Interest, Activity.Type.FX]:
            effect[self.cash] = self.netAmount

        elif self.type in [Activity.Type.Expiry, Activity.Type.Journal]:
            effect[self.security] = self.qty

        return effect
    
class Allocation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE, related_name='allocations')
    securities = models.ManyToManyField(Security)
    desired_pct = models.DecimalField(max_digits=6, decimal_places=4)

    def __str__(self):
        return "{} - {} - {}".format(self.user, self.desired_pct, self.list_securities())

    def __repr__(self):
        return "Allocation<{},{},{}>".format(self.user, self.desired_pct, self.list_securities())

    def list_securities(self):
        return ', '.join([s.symbol for s in self.securities.all()])


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    plotly_url = models.CharField(max_length=500, null=True, blank=True)

    def GetHeldSecurities(self):
        return Holding.objects.for_user(self.user
               ).current().values_list('security_id', flat=True).distinct()
    
    def GetTaxableSecurities(self):
        return Holding.objects.filter(
            account__taxable=True
            ).exclude(security__type=Security.Type.Cash
            ).for_user(self.user).current().values_list('security_id', flat=True).distinct()

    def GetAccounts(self):
        return BaseAccount.objects.filter(client__user=self.user)

    @property
    def portfolio_iframe(self):
        return plotly_iframe_from_url(self.plotly_url)


class HoldingDetailQuerySet(models.query.QuerySet):    
    def for_user(self, user):
        return self.filter(account__client__user=user)
    
    def at_date(self, date):
        return self.filter(day=date)

    def at_dates(self, startdate, enddate=datetime.date.today()):
        return self.filter(day__range=(startdate, enddate))

    def today(self):
        return self.at_date(datetime.date.today())

    def yesterday(self):
        return self.at_date(datetime.date.today() - datetime.timedelta(days=1))
    
    def cash(self):
        return self.filter(type=Security.Type.Cash)
    
    def week_end(self):
        return self.filter( day__in=utils.dates.week_ends(self.earliest().day) )
    
    def month_end(self):
        return self.filter( day__in=utils.dates.month_ends(self.earliest().day) )
    
    def year_end(self):
        return self.filter( day__in=utils.dates.year_ends(self.earliest().day) )

    def account_values(self):
        return self.values_list('account','day').annotate(Sum('value'))

    def total_values(self):
        return self.values_list('day').annotate(Sum('value'))

    def by_security(self, by_account=False):
        columns = ['security','day']
        if by_account:
            columns.insert(1,'account')
        return self.values(*columns, 'price','exch','cad',
            ).annotate(total_qty=Sum('qty'), total_val=Sum('value')
            ).order_by(*columns)


class HoldingDetail(models.Model):
    account = models.ForeignKey(BaseAccount, on_delete=models.DO_NOTHING)
    security = models.ForeignKey(Security, on_delete=models.DO_NOTHING)
    day = models.DateField()
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    exch = models.DecimalField(max_digits=16, decimal_places=6)
    cad = models.DecimalField(max_digits=16, decimal_places=6)
    value = models.DecimalField(max_digits=16, decimal_places=6)

    objects = HoldingDetailQuerySet.as_manager()            

    @classmethod
    def CreateView(cls):
        cursor = connection.cursor()
        try:
            cursor.execute("""DROP MATERIALIZED VIEW financeview_securitycadprices CASCADE;""")
            cursor.execute("""
CREATE MATERIALIZED VIEW public.financeview_securitycadprices
AS
 SELECT sec.day,
    sec.symbol,
    sec.price,
    er.price AS exch,
    sec.price * er.price AS cadprice
   FROM ( SELECT s.symbol,
            s.currency_id,
            sp.day,
            sp.price
           FROM finance_security s
             JOIN finance_securityprice sp ON s.symbol::text = sp.security_id::text) sec
     JOIN finance_exchangerate er ON sec.day = er.day AND sec.currency_id::text = er.currency_id::text
WITH DATA;""")
            cursor.execute("""
CREATE MATERIALIZED VIEW financeview_holdingdetail
TABLESPACE pg_default
AS
 SELECT h.account_id,
    h.security_id,
    p.day,
    h.qty,
    p.price,
    p.exch,
    p.cadprice AS cad,
    p.cadprice * h.qty AS value,
    row_number() OVER () AS id
   FROM finance_holding h
     JOIN financeview_securitycadprices p ON h.security_id::text = p.symbol::text AND h.startdate <= p.day AND (p.day <= h.enddate OR h.enddate IS NULL)
WITH DATA;""")
            cursor.execute("ALTER TABLE financeview_securitycadprices OWNER TO financeuser;")
            cursor.execute("ALTER TABLE financeview_holdingdetail OWNER TO financeuser;")
            connection.commit()
        finally:
            cursor.close()

    @classmethod
        cursor = connection.cursor()
        try:
            cursor.execute("REFRESH MATERIALIZED VIEW financeview_securitycadprices;")
            cursor.execute("REFRESH MATERIALIZED VIEW financeview_holdingdetail;")
            connection.commit()
        finally:
            cursor.close()

    class Meta:
        managed = False
        db_table = 'financeview_holdingdetail'
        get_latest_by = 'day'
        ordering = ['day']

    def __str__(self):
        return '{} {} {} {:.2f} {:.2f} {:.4f} {:.2f} {:.2f}'.format(
            self.account_id, self.day, self.security_id, self.qty, 
            self.price, self.exch, self.cad, self.value)

    def __repr__(self):
        return '{} {} {} {:.2f} {:.2f} {:.4f} {:.2f} {:.2f}'.format(
            self.account_id, self.day, self.security_id, self.qty, 
            self.price, self.exch, self.cad, self.value)
