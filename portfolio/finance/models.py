from django.db import models, transaction
from django.core.exceptions import ObjectDoesNotExist
from polymorphic.models import PolymorphicModel
from django.db.models import F, Max, Q, Sum

from collections import defaultdict
from decimal import Decimal
import datetime
from model_utils import Choices
import arrow
import pandas
import numpy
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
        
    def GetShouldSyncRange(self):
        """ Returns a pair (start,end) of datetime.dates that need to be synced."""
        latest = datetime.date(2009,1,1)
        try:
            latest = self.rates.latest().day
        except ObjectDoesNotExist:
            pass

        if latest == datetime.date.today():
            return (None, None)

        start_date = latest - datetime.timedelta(days=7)
        end_date = datetime.date.today()
        return (start_date, end_date)
        
    @property
    def live_price(self):
        try:
            return self.rates.get(day=datetime.date.today()).price
        except:
            return self.rates.latest().price

    @live_price.setter
    def live_price(self, value):
        self.rates.update_or_create(day=datetime.date.today(), defaults={'price':value})

    def _ProcessRateData(self, data, end_date):
        if not data: return []
        if isinstance(data, pandas.DataFrame):
            data = pandas.Series(data[self.lookupColumn], data.index)
        else:
            # Expect iterator of day, price pairs
            dates, prices = zip(*data)
            data = pandas.Series(prices, index=dates)

        data = data.sort_index()
        data = data.replace(0,numpy.nan)
        index = pandas.DatetimeIndex(start = min(data.index), end=end_date, freq='D').date
        data = data.reindex(index).ffill()
        return data.iteritems()

    def SyncRates(self, retriever_fn):
        """ 
        retriever_fn is the function that will retrieve the rates.
        It gets passed (lookup, start, end) and is expected to return an iterator of (day, price) pairs or a pandas dataframe
        """
        start, end = self.GetShouldSyncRange()
        if start is None:
            print ('Already synced data for {}, skipping.'.format(self.lookupSymbol))
            return []

        data = self._ProcessRateData(retriever_fn(self, start, end), end)
        
        with transaction.atomic():
            for day, price in data:
                self.rates.update_or_create(day=day, defaults={'price':price})      
                    
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
        
    def GetExchangeRate(self, day):
        return self.GetRate(day)
        
class StockSecurityManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.Stock)
    
class CashSecurityManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.Cash)
    
class OptionSecurityManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.Option)

class MutualFundSecurityManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.MutualFund)

class Security(RateLookupMixin):
    Type = Choices('Stock', 'Option', 'Cash', 'MutualFund')

    symbol = models.CharField(max_length=32, primary_key=True)
    symbolid = models.BigIntegerField(default=0)
    description = models.CharField(max_length=500, null=True, blank=True, default='')
    type = models.CharField(max_length=12, choices=Type, default=Type.Stock)
    listingExchange = models.CharField(max_length=20, null=True, blank=True, default='')
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE) 

    objects = models.Manager()
    stocks = StockSecurityManager()
    cash = CashSecurityManager()
    options = OptionSecurityManager()
    mutualfunds = MutualFundSecurityManager()

    @classmethod
    def CreateFromJson(cls, json):
        Security.objects.update_or_create(
            symbolid = json['symbolId']
            , symbol = json['symbol']
            , description = json['description']
            , type = json['securityType']
            , listingExchange = json['listingExchange']
            , currency_id = json['currency']
            )
      
    class Meta:
        verbose_name_plural = 'Securities'
        
    @property
    def live_price_cad(self):
        return self.live_price * self.currency.live_price
        
    def GetPrice(self, day):
        return self.GetRateOnDay(day)

    def GetPriceCAD(self, day):
        return self.GetRateOnDay(day) * self.currency.GetRateOnDay(day)

    def __str__(self):
        return "{} {}".format(self.symbol, self.currency)

    def __repr(self):
        return "Security({} {} ({}) {} {})".format(self.symbol, self.symbolid, self.currency, self.listingExchange, self.description)   

class SecurityPrice(RateHistoryTableMixin):
    security = models.ForeignKey(Security, on_delete=models.CASCADE, related_name='rates')

    class Meta:
        unique_together = ('security', 'day')
        get_latest_by = 'day'
        indexes = [
            models.Index(fields=['security', 'day']),
            models.Index(fields=['day'])
        ]

    def __str__(self):
        return "{} {} {}".format(self.security, self.day, self.price)

class ExchangeRate(RateHistoryTableMixin):
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='rates')

    class Meta:
        unique_together = ('currency', 'day')
        get_latest_by = 'day'
        indexes = [
            models.Index(fields=['currency', 'day']),
            models.Index(fields=['day'])
        ]

    def __str__(self):
        return "{} {} {}".format(self.currency, self.day, self.price)   
  

class DataProvider:
    FAKED_VALS = {'DLR.U.TO':10.}

    @classmethod
    def _FakeData(cls, lookup, start, end):
        for day in pandas.date_range(start, end).date:
            yield day, 1.
    
    @classmethod
    def _RetrievePandasData(cls, lookup, start, end):
        """ Returns a list of tuples (day, price) """
        FAKED_VALS = {'DLR.U.TO':10.}
        if lookup.lookupSymbol in cls.FAKED_VALS:
            index = pandas.date_range(start, end, freq='D').date
            return zip(index, pandas.Series(cls.FAKED_VALS[lookup.lookupSymbol], index))

        print('Syncing prices for {} from {} to {}...'.format(lookup.lookupSymbol, start, end))
        for retry in range(5):
            try: 
                df = pdr.DataReader(lookup.lookupSymbol, lookup.lookupSource, start, end)
                if df.size == 0:
                    return
                ix = pandas.DatetimeIndex(start=min(df.index), end=end, freq='D')
                df = df.reindex(ix).ffill()
                return zip(ix, df[lookup.lookupColumn])
            except: 
                pass
        return    
    
    @classmethod
    def GetAlphaVantageData(cls, lookup, start, end):
        fake = {'DLR.U.TO':10., 'CAD':1.}
        if lookup.lookupSymbol in fake:
            index = pandas.date_range(start, end, freq='D').date
            return zip(index, pandas.Series(fake[lookup.lookupSymbol], index))

        print('Syncing prices for {} from {} to {}...'.format(lookup.lookupSymbol, start, end))
        params={'function':'TIME_SERIES_DAILY', 'symbol':lookup.lookupSymbol, 'apikey':'P38D2XH1GFHST85V'}
        if (end - start).days > 100: params['outputsize'] = 'full'
        r = requests.get('https://www.alphavantage.co/query', params=params)
        json = r.json()
        if 'Time Series (Daily)' in json:
            return [(parser.parse(day).date(), Decimal(vals['4. close'])) for day,vals in json['Time Series (Daily)'].items() if str(start) <= day <= str(end)]        
        return []

    @classmethod
    def GetLiveStockPrice(cls, symbol):
        symbol = symbol.split('.')[0]
        params={'function':'TIME_SERIES_INTRADAY', 'symbol':symbol, 'apikey':'P38D2XH1GFHST85V', 'interval':'1min'}        
        r = requests.get('https://www.alphavantage.co/query', params=params)
        json = r.json()
        price = Decimal(0)
        if 'Time Series (1min)' in json:
            newest = json["Meta Data"]["3. Last Refreshed"]
            price = Decimal(json['Time Series (1min)'][newest]['4. close'])
        print('Getting live price for {}... {}'.format(symbol, price))        
        return price
                    
    @classmethod
    def SyncAllSecurities(cls):
        for stock in Security.stocks.all():
            stock.SyncRates(cls.GetAlphaVantageData)
            if Holding.current.filter(security=stock).exists():
                stock.live_price = cls.GetLiveStockPrice(stock.symbol)

        # Just generate fake 1 entries so we can join these tables later.
        for cash in Security.cash.all():
            cash.SyncRates(cls._FakeData)

    @classmethod
    def SyncAllExchangeRates(cls):
        for currency in Currency.objects.all():
            Security.objects.get_or_create(symbol=currency.code + ' Cash', currency=currency, type=Security.Type.Cash)
            currency.SyncRates(cls._FakeData if currency.code == 'CAD' else cls._RetrievePandasData)

        r = requests.get('https://openexchangerates.org/api/latest.json', params={'app_id':'eb324bcd04b743c2830360072d84e024', 'symbols':'CAD'})
        Currency.objects.get(code='USD').live_price = Decimal(str(r.json()['rates']['CAD']))


class BaseClient(PolymorphicModel):
    username = models.CharField(max_length=10, primary_key=True)

    @classmethod 
    def Get(cls, username):
        client = cls.objects.get(username=username)
        client.Authorize()
        return client

    @property
    def activitySyncDateRange(self):
        return 30

    def __str__(self):
        return self.username
        
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

    def _CreateRawActivities(account_id, start, end):
        pass
        
    def SyncActivities(self, startDate='2011-01-01'):
        for account in self.accounts.all():            
            print ('Syncing all activities for {}: '.format(account), end='')
            start = account.GetMostRecentActivityDate()
            if start: start = arrow.get(start).shift(days=+1)
            else: start = arrow.get(startDate)
            
            account.rawactivities.all().delete()
            date_range = arrow.Arrow.interval('day', start, arrow.now(), self.activitySyncDateRange)
            print('{} requests'.format(len(date_range)), end='')
            for start, end in date_range:
                print('.',end='', flush=True)
                account._CreateRawActivities(start, end)

    def SyncPrices(self):
        pass

    def SyncCurrentAccountBalances(self):
        pass
    
    
class BaseAccount(PolymorphicModel):
    client = models.ForeignKey(BaseClient, on_delete=models.CASCADE, related_name='accounts')
    type = models.CharField(max_length=100)
    id = models.IntegerField(default=0, primary_key = True)

    class Meta:
        ordering = ['id']
        
    def __repr__(self):
        return "BaseAccount({},{},{})".format(self.client, self.id, self.type)

    def __str__(self):
        return "{} {} {}".format(self.client, self.id, self.type)

    @property
    def display_name(self):
        return "{} {}".format(self.client.username, self.type)

    @property
    def cur_balance(self):
        return 0
        #return self.GetValueAtDate(datetime.date.today())

    @property
    def yesterday_balance(self):
        return 0
        #return self.GetValueAtDate(datetime.date.today() - datetime.timedelta(days=1))

    def RegenerateActivities(self):
        self.activities.all().delete()      
        all_activities = [raw.CreateActivity() for raw in self.rawactivities.all()]
        Activity.objects.bulk_create([a for a in all_activities if a is not None])      
                    
    def RegenerateHoldings(self):
        self.holding_set.all().delete()
        self.HackInit()
        for activity in self.activities.all():          
            for security, qty_delta in activity.GetHoldingEffect().items():
                self.holding_set.add_effect(self, security, qty_delta, activity.tradeDate)
        self.holding_set.filter(qty=0).delete()

    def HackInit(self):
        pass
    
    def GetValueList(self, date):
        Holding.objects.filter(
            Q(enddate__gte=date)|Q(enddate=None), 
            account=self,
            startdate__lte=date, 
            security__rates__day=date, 
            security__currency__rates__day=date).aggregate(
                val=Sum(F('qty')*F('security__rates__price')*F('security__currency__rates__price')
            )
        )['val']        
        
                     
    def GetMostRecentActivityDate(self):
        try:
            return self.activities.latest().tradeDate
        except:
            return None

    def GetValueAtDate(self, date):
        return self.GetValueList()[date]
    
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
                    
    def CreateActivity(self): 
        if self.security:
            type = Security.Type.Stock if len(self.security) < 20 else Security.Type.Option
            security, created = Security.objects.get_or_create(symbol=self.security, defaults={'currency_id':'USD', 'type':type})
        else:
            security = None

        a = Activity(account=self.account, tradeDate=self.day, security=security, description=self.description, cash_id=self.cash, qty=self.qty, 
                        price=self.price, netAmount=self.netAmount, type=self.type, raw=self)

        if not a.cash_id:
            a.cash = None
        return a
             
class HoldingManager(models.Manager):
    def at_date(self, date):
        return self.filter(startdate__lte=date).exclude(enddate__lt=date).exclude(qty=0)

    def add_effect(self, account, security, qty_delta, date):                       
        previous_qty = 0
        try:
            samedate_q = self.filter(security=security, startdate=date, enddate=None)
            if samedate_q:
                obj = samedate_q[0]
                obj.qty += qty_delta
                if obj.qty == 0:
                    obj.delete()
                else:
                    obj.save()
                return

            current_holding = self.get(security=security, enddate=None)
            current_holding.enddate = date - datetime.timedelta(days=1)
            previous_qty = current_holding.qty
            #print ("Updated old {} enddate({}) prev {}".format(security, current_holding.enddate, previous_qty))
            current_holding.save(update_fields=['enddate'])

        except Holding.MultipleObjectsReturned:
            print("HoldingManager.add_effect() returned multiple holdings for query {} {} {}".format(security))
        except Holding.DoesNotExist:
            pass

        new_qty = previous_qty+qty_delta
        if new_qty:
            print ("Creating {} {} {} {}".format(security, new_qty, date, None))
            self.create(account=account,security=security, qty=new_qty, startdate=date, enddate=None)
            
class CurrentHoldingManager(HoldingManager):
    def get_queryset(self):
        return super().get_queryset().filter(enddate=None)

class Holding(models.Model):
    account = models.ForeignKey(BaseAccount, on_delete=models.CASCADE)
    security = models.ForeignKey(Security, on_delete=models.CASCADE, related_name='holdings')
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    startdate = models.DateField()
    enddate = models.DateField(null=True)
    
    objects = HoldingManager()
    current = CurrentHoldingManager()

    class Meta:
        unique_together = ('account', 'security', 'startdate')
        get_latest_by = 'startdate'

    def __repr__(self):
        return "Holding({},{},{},{},{})".format(self.account, self.security, self.qty, self.startdate, self.enddate)

    
class Activity(models.Model):
    account = models.ForeignKey(BaseAccount, on_delete=models.CASCADE, related_name='activities')
    tradeDate = models.DateField()
    security = models.ForeignKey(Security, on_delete=models.CASCADE, null=True, related_name='dontaccess_security')
    description = models.CharField(max_length=1000)
    cash = models.ForeignKey(Security, on_delete=models.CASCADE, null=True, related_name='dontaccess_cash')
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    netAmount = models.DecimalField(max_digits=16, decimal_places=2)
    Type = Choices('Deposit', 'Dividend', 'FX', 'Fee', 'Interest', 'Buy', 'Sell', 'Transfer', 'Withdrawal', 'Expiry', 'Journal', 'NotImplemented')
    type = models.CharField(max_length=100, choices=Type)
    raw = models.OneToOneField(BaseRawActivity, on_delete=models.CASCADE)
    
    class Meta:
        unique_together = ('account', 'tradeDate', 'security', 'cash', 'qty', 'price', 'netAmount', 'type', 'description')
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
            effect[self.cash] = self.netAmount

        elif self.type in [Activity.Type.Transfer, Activity.Type.Dividend, Activity.Type.Fee, Activity.Type.Interest, Activity.Type.FX]:
            effect[self.cash] = self.netAmount
            
        elif self.type in [Activity.Type.Expiry, Activity.Type.Journal]:
            effect[self.security] = self.qty

        return effect                 
    
    
def GetHistoryValues(startdate=None):
    """ Returns an (date, value) tuple for each date where the value of that account is > 0 """
    if startdate is None: 
        pricequery = SecurityPrice.objects.all()
    else:
        pricequery = SecurityPrice.objects.filter(day__gte=startdate)
    
    val_list = pricequery.filter(
        Q(security__holdings__enddate__gte=F('day'))|Q(security__holdings__enddate=None), 
        security__holdings__startdate__lte=F('day'),
        security__currency__rates__day=F('day')
    ).order_by('day').values_list('day').annotate( val=Sum(F('price') * F('security__holdings__qty') * F('security__currency__rates__price')) )
    
    return val_list

def GetValueDataFrame(startdate=None):
    """ Returns an (account, date, value) tuple for each date where the value of that account is > 0 """
    if startdate is None: 
        pricequery = SecurityPrice.objects.all()
    else:
        pricequery = SecurityPrice.objects.filter(day__gte=startdate)
    
    val_list = pricequery.filter(
        Q(security__holdings__enddate__gte=F('day'))|Q(security__holdings__enddate=None), 
        security__holdings__startdate__lte=F('day'),
        security__currency__rates__day=F('day')
    ).values_list('day', 'security__holdings__account_id').annotate(
        val=Sum(F('price') * F('security__holdings__qty') * F('security__currency__rates__price'))
    )

    all_accounts = BaseAccount.objects.all()
    dates = sorted(list({d for d,a,v in val_list}))

    vals = defaultdict(dict)
    for d,a,v in val_list:
        vals[a][pandas.Timestamp(d)] = v
    
    s = [pandas.Series(vals[a.id], name=a.display_name) for a in all_accounts]
    df = pandas.DataFrame(s).T.fillna(0).astype(int).iloc[::-1]
    df = df.assign(Total=pandas.Series(df.sum(1)))
    df.index = df.index.date
    return df
