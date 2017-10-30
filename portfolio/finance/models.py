from django.db import models, transaction
from django.core.exceptions import ObjectDoesNotExist
from polymorphic.models import PolymorphicModel
from django.db.models import F, Max, Q, Sum

from collections import defaultdict
from decimal import Decimal
import datetime
from model_utils import Choices

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
    lookupSymbol = models.CharField(max_length=16, null=True, blank=True, default=None)
    lookupSource = models.CharField(max_length=16, null=True, blank=True, default=None)
    lookupColumn = models.CharField(max_length=10, null=True, blank=True, default=None)    
    livePrice = models.DecimalField(max_digits=19, decimal_places=6, default=0)   
        
    def GetLatestEntryDate(self):
        try:
            return self.rates.latest().day
        except ObjectDoesNotExist:
            return datetime.date(2009,1,1)

    def GetLatestRate(self):
        return self.rates.latest().price
                
    def GetRate(self, day):
        return self.rates.get(day=day).price
        
    def save(self, *args, **kwargs):
        if hasattr(self, 'symbol'): 
            self.lookupSymbol = self.symbol
            self.lookupSource = 'yahoo'
            self.lookupColumn = 'Close'
        super().save(*args, **kwargs)

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
        
    def GetPrice(self, day):
        return self.GetRate(day)

    def GetLatestPrice(self):
        return self.GetLatestRate()

    def GetPriceCAD(self, day):
        return self.GetRate(day) * self.currency.GetRate(day)

    def GetLatestPriceCAD(self):
        return self.GetLatestRate() * self.currency.GetLatestRate()

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
    FAKED_VALS = {'DLR.U.TO':10., None:1., 'USD Cash':1., 'CAD Cash':1.}
    
    @classmethod
    def _RetrieveData(cls, lookup):
        """ Returns a list of tuples (day, price) """
        start_date = lookup.GetLatestEntryDate() + datetime.timedelta(days=1)
        end_date = datetime.date.today() - datetime.timedelta(days=1)
        if start_date >= end_date:
            print ('Already synced data for {}, skipping.'.format(lookup.lookupSymbol))
            return []

        if lookup.lookupSymbol in cls.FAKED_VALS:
            index = pandas.date_range(start_date, end_date, freq='D').date
            return zip(index, pandas.Series(cls.FAKED_VALS[lookup.lookupSymbol], index))

        print('Syncing prices for {} from {} to {}...'.format(lookup.lookupSymbol, start_date, end_date))
        df = pdr.DataReader(lookup.lookupSymbol, lookup.lookupSource, start_date, end_date, retry_count=5)
        if df.size == 0:
            return []
        ix = pandas.DatetimeIndex(start=min(df.index), end=end_date, freq='D')
        df = df.reindex(ix).ffill()
        return zip(ix, df[lookup.lookupColumn])

        return []
     
    @classmethod
    def SyncStockPrices(cls, security):
        data = cls._RetrieveData(security)
        security.rates.bulk_create([SecurityPrice(security=security, day=day, price=price) for day, price in data])

    @classmethod
    def SyncExchangeRates(cls, currency):
        data = cls._RetrieveData(currency)
        currency.rates.bulk_create([ExchangeRate(currency=currency, day=day, price=price) for day, price in data])
        
    @classmethod
    def Init(cls):        
        Currency.objects.update_or_create(code='CAD')
        Currency.objects.update_or_create(code='USD', lookupSymbol='DEXCAUS', lookupSource='fred', lookupColumn='DEXCAUS')
        for currency in Currency.objects.all():
            Security.objects.update_or_create(symbol=currency.code + ' Cash', currency=currency, type=Security.Type.Cash)
            cls.SyncExchangeRates(currency)
            
    @classmethod
    def SyncAllSecurities(cls):
        for stock in Security.stocks.all():
            cls.SyncStockPrices(stock)

        # Just generate fake 1 entries so we can join these tables later.
        for cash in Security.cash.all():
            cls.SyncStockPrices(cash)


class BaseClient(PolymorphicModel):
    username = models.CharField(max_length=10, primary_key=True)

    @classmethod 
    def Get(cls, username):
        client = cls.objects.get(username=username)
        client.Authorize()
        return client

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
    
    
class BaseAccount(PolymorphicModel):
    client = models.ForeignKey(BaseClient, on_delete=models.CASCADE, related_name='accounts')
    type = models.CharField(max_length=100)
    id = models.IntegerField(default=0, primary_key = True)
        
    def __repr__(self):
        return "BaseAccount({},{},{})".format(self.client, self.id, self.type)

    def __str__(self):
        return "{} {} {}".format(self.client, self.id, self.type)

    @property
    def display_name(self):
        return "{} {}".format(self.client.username, self.type)

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
    
    def GetMostRecentActivityDate(self):
        try:
            return self.activities.latest().tradeDate
        except:
            return None
            
    def GetValueList(self):
        val_list = SecurityPrice.objects.filter(
            Q(security__holding__enddate__gte=F('day'))|Q(security__holding__enddate=None), 
            security__holding__startdate__lte=F('day'),
            security__holding__account_id=self.id, 
            security__currency__rates__day=F('day')
        ).values_list('day').annotate(
            val=Sum(F('price') * F('security__holding__qty') * F('security__currency__rates__price'))
        )
        d = defaultdict(int)
        d.update({date:val for date,val in val_list})
        return d

    def GetValueAtDate(self, date):
        return self.GetValueList()[date]
            
        
class BaseRawActivity(PolymorphicModel):    
    account = models.ForeignKey(BaseAccount, on_delete=models.CASCADE, related_name='rawactivities')
                    
    def CreateActivity(self): 
        pass
             
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
    security = models.ForeignKey(Security, on_delete=models.CASCADE)
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