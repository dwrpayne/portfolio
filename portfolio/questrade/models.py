from django.db import models, transaction
from django.core.exceptions import ObjectDoesNotExist
from django.db.utils import IntegrityError
from django.utils import timezone
from django.db.models import F, Max, Q, Sum
from model_utils import Choices
from model_utils.managers import InheritanceManager

import requests
import os
import sys
import operator
from dateutil import parser
import arrow
from collections import defaultdict
import logging 
import copy
import datetime
from decimal import Decimal
import traceback
import simplejson
import threading

import pandas
from pandas_datareader import data as pdr

#logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

    def sync_all(self):
        for stock in get_queryset(): 
            DataProvider.SyncStockPrices(stock)

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
        df = pdr.DataReader(lookup.lookupSymbol, lookup.lookupSource, start_date, end_date, retry_count=5, pause=1.0)
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
        Currency.objects.update_or_create(code='USD', lookupSymbol='FXUSDCAD', lookupSource='bankofcanada', lookupColumn='FXUSDCAD')
        for currency in Currency.objects.all():
            Security.objects.update_or_create(symbol=currency.code + ' Cash', currency=currency, type=Security.Type.Cash)
            cls.SyncExchangeRates(currency)
            
    @classmethod
    def SyncAllSecurities(cls):
        Security.stocks.sync_all()

        # Just generate fake 1 entries so we can join these tables later.
        for cash in Security.cash.all():
            cls.SyncStockPrices(cash)

class ActivityJson(models.Model):
    jsonstr = models.CharField(max_length=1000)
    cleaned = models.CharField(max_length=1000, null=True, blank=True)
    account = models.ForeignKey('Account', on_delete=models.CASCADE)
    
    class Meta:
        unique_together = ('jsonstr', 'account')

    def __str__(self):
        return self.jsonstr

    @classmethod 
    def Add(cls, json, account):
        s = simplejson.dumps(json)        
        obj, created = ActivityJson.objects.update_or_create(jsonstr=s, account=account)
        if not created and cls.AllowDuplicate(s):
            s = s.replace('YOUR ACCOUNT   ', 'YOUR ACCOUNT X2')
            ActivityJson.objects.create(jsonstr=s, account=account)

    @classmethod
    def GetActivityType(cls, type, action):
        mapping = {('Deposits', 'CON'): Activity.Type.Deposit,
                   ('Deposits', 'CSP'): Activity.Type.Deposit,
                   ('Deposits', 'DEP'): Activity.Type.Deposit,
                   ('Fees and rebates', 'FCH'): Activity.Type.Fee,
                   ('FX conversion', 'FXT'): Activity.Type.FX,
                   ('Other', 'EXP'): Activity.Type.Expiry,
                   ('Other', 'BRW'): Activity.Type.Journal,
                   ('Trades', 'Buy'): Activity.Type.Buy,
                   ('Trades', 'Sell'): Activity.Type.Sell,
                   ('Withdrawals', 'CON'): Activity.Type.Withdrawal,
                   ('Transfers', 'TF6'): Activity.Type.Transfer,
                   ('Dividends', 'DIV'): Activity.Type.Dividend,
                   ('Dividends', ''): Activity.Type.Dividend,
                   ('Dividends', '   '): Activity.Type.Dividend,
                   ('Dividends', 'NRT'): Activity.Type.Dividend,
                   ('Interest', '   '): Activity.Type.Interest
                   }
        if (type, action) in mapping: return mapping[(type, action)]
        print ('No action type mapping for "{}" "{}"'.format(type, action))
        return None
    
    @classmethod
    def AllowDuplicate(cls, s):        
        # Hack to support actual duplicate transactions (no disambiguation available)
        return s == '{"tradeDate": "2012-08-17T00:00:00.000000-04:00", "transactionDate": "2012-08-20T00:00:00.000000-04:00", "settlementDate": "2012-08-20T00:00:00.000000-04:00", "action": "Sell", "symbol": "", "symbolId": 0, "description": "CALL EWJ    01/19/13    10     ISHARES MSCI JAPAN INDEX FD    AS AGENTS, WE HAVE BOUGHT      OR SOLD FOR YOUR ACCOUNT   ", "currency": "USD", "quantity": -5, "price": 0.14, "grossAmount": null, "commission": -14.96, "netAmount": 55.04, "type": "Trades"}'

    def CleanSourceData(self):
        json = simplejson.loads(self.jsonstr)

        if json['grossAmount'] == None:
            json['grossAmount'] = 0
            
        # Handle Options cleanup
        if json['description'].startswith('CALL ') or json['description'].startswith('PUT '):
            type, symbol, expiry, strike = json['description'].split()[:4]
            symbol = symbol.strip('.7')
            expiry = datetime.datetime.strptime(expiry, '%m/%d/%y').strftime('%y%m%d')
            optionsymbol = "{:<6}{}{}{:0>8}".format(symbol, expiry, type[0], Decimal(strike)*1000)
            json['symbol'] = optionsymbol

        # Hack to fix invalid Questrade data just for me   
        if not json['symbolId'] and not json['symbol']:
            if 'ISHARES S&P/TSX 60 INDEX' in json['description']:          json['symbol']='XIU.TO'
            elif 'VANGUARD GROWTH ETF' in json['description']:             json['symbol']='VUG'
            elif 'SMALLCAP GROWTH ETF' in json['description']:             json['symbol']='VBK'
            elif 'SMALL-CAP VALUE ETF' in json['description']:             json['symbol']='VBR'
            elif 'ISHARES MSCI EAFE INDEX' in json['description']:         json['symbol']='XIN.TO'
            elif 'AMERICAN CAPITAL AGENCY CORP' in json['description']:    json['symbol']='AGNC'
            elif 'MSCI JAPAN INDEX FD' in json['description']:             json['symbol']='EWJ'
            elif 'VANGUARD EMERGING' in json['description']:               json['symbol']='VWO'
            elif 'VANGUARD MID-CAP GROWTH' in json['description']:         json['symbol']='VOT'
            elif 'ISHARES DEX SHORT TERM BOND' in json['description']:     json['symbol']='XBB.TO'
            elif 'ELECTRONIC ARTS INC' in json['description']:             json['symbol']='EA'
            elif 'WESTJET AIRLINES' in json['description']:                json['symbol']='WJA.TO'         
            
        if json['symbol'] == 'TWMJF':
            json['currency'] = 'USD'

        if json['action'] =='FXT':
            if 'AS OF ' in json['description']:
                tradeDate = arrow.get(json['tradeDate'])

                asof = arrow.get(json['description'].split('AS OF ')[1].split(' ')[0], 'MM/DD/YY')
                #print("FXT Transaction at {} (asof date: {}). Timedelta is {}".format(tradeDate, asof, tradeDate-asof))
                if (tradeDate-asof).days > 365:
                    asof = asof.shift(years=+1)

                json['tradeDate'] = tradeDate.replace(year=asof.year, month=asof.month, day=asof.day).isoformat()

        for item in ['tradeDate']:
            json[item] = str(parser.parse(json[item].date()))

        json['type'] = self.GetActivityType(json['type'], json['action'])
        json['qty'] = json['quantity']
        del json['quantity']
                        
        if json['currency'] == json['symbol']:
            json['symbol'] = None
            
        self.cleaned = simplejson.dumps(json)
        self.save(update_fields=['cleaned'])
        
    def CreateActivity(self): 
        json = simplejson.loads(self.cleaned)
                
        create_args = {'account' : self.account, 'sourcejson' : self}
        for item in ['description', 'tradeDate', 'type']:
            create_args[item] = json[item]
        for item in ['price', 'netAmount', 'qty']:
            create_args[item] = Decimal(str(json[item])) 
            
        if json['symbol']: 
            try:
                type = Security.Type.Stock if len(json['symbol']) < 20 else Security.Type.Option
                create_args['security'], created = Security.objects.get_or_create(symbol=json['symbol'], currency_id=json['currency'], type=type)
            except:
                print ("Couldn't create {} {}".format(json['symbol'], json['currency']))
            
        else:
            create_args['security'] = None

        create_args['cash_id'] = json['currency']+' Cash'
            
        activity = Activity(**create_args)
        return activity

class Activity(models.Model):
    account = models.ForeignKey('Account', on_delete=models.CASCADE)
    tradeDate = models.DateField()
    security = models.ForeignKey(Security, on_delete=models.CASCADE, null=True, related_name='dontaccess_security')
    description = models.CharField(max_length=1000)
    cash = models.ForeignKey(Security, on_delete=models.CASCADE, null=True, related_name='dontaccess_cash')
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    netAmount = models.DecimalField(max_digits=16, decimal_places=2)
    Type = Choices('Deposit', 'Dividend', 'FX', 'Fee', 'Interest', 'Buy', 'Sell', 'Transfer', 'Withdrawal', 'Expiry', 'Journal')
    type = models.CharField(max_length=100, choices=Type)
    sourcejson = models.ForeignKey(ActivityJson, on_delete=models.CASCADE)
    
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
    account = models.ForeignKey('Account', on_delete=models.CASCADE)
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

class Account(models.Model):
    client = models.ForeignKey('Client', on_delete=models.CASCADE, related_name='accounts')
    type = models.CharField(max_length=100)
    id = models.IntegerField(default=0, primary_key = True)
    curBalanceSynced = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    sodBalanceSynced = models.DecimalField(max_digits=19, decimal_places=4, default=0)
        
    def __repr__(self):
        return "Account({},{},{})".format(self.client, self.id, self.type)

    def __str__(self):
        return "{} {} {}".format(self.client, self.id, self.type)

    @property
    def display_name(self):
        return "{} {}".format(self.client.username, self.type)
    
    def GetMostRecentActivityDate(self):
        try:
            return self.activity_set.latest().tradeDate
        except:
            return None
            
    def RegenerateHoldings(self):
        self.holding_set.all().delete()
        self.HackInitMyAccount()
        for activity in self.activity_set.all():          
            for security, qty_delta in activity.GetHoldingEffect().items():
                self.holding_set.add_effect(self, security, qty_delta, activity.tradeDate)
        self.holding_set.filter(qty=0).delete()

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
    
    def RegenerateActivities(self):
        with transaction.atomic():
            for activityjson in self.activityjson_set.all():
                activityjson.CleanSourceData()
        self.activity_set.all().delete()
        all_activities = [j.CreateActivity() for j in self.activityjson_set.all()]
        Activity.objects.bulk_create([a for a in all_activities if a is not None])
        
    def HackInitMyAccount(self):
        start = '2011-01-01'
        if self.id == 51407958:
            self.holding_set.create(security_id='AGNC', qty=70, startdate=start, enddate=None)
            self.holding_set.create(security_id='VBK', qty=34, startdate=start, enddate=None)
            self.holding_set.create(security_id='VUG', qty=118, startdate=start, enddate=None)
            self.holding_set.create(security_id='CAD Cash', qty=Decimal('92.30'), startdate=start, enddate=None)
            self.holding_set.create(security_id='USD Cash', qty=Decimal('163.62'), startdate=start, enddate=None)

        if self.id == 51424829:     
            self.holding_set.create(security_id='EA', qty=300, startdate=start, enddate=None)
            self.holding_set.create(security_id='VOT', qty=120, startdate=start, enddate=None)
            self.holding_set.create(security_id='VWO', qty=220, startdate=start, enddate=None)
            self.holding_set.create(security_id='XSB.TO', qty=260, startdate=start, enddate=None)
            self.holding_set.create(security_id='XIU.TO', qty=200, startdate=start, enddate=None)
            self.holding_set.create(security_id='USD Cash', qty=Decimal('-118.3'), startdate=start, enddate=None)

        if self.id == 51419220:     
            self.holding_set.create(security_id='VBR', qty=90, startdate=start, enddate=None)
            self.holding_set.create(security_id='XSB.TO', qty=85, startdate=start, enddate=None)
            self.holding_set.create(security_id='XIN.TO', qty=140, startdate=start, enddate=None)
            self.holding_set.create(security_id='CAD Cash', qty=Decimal('147.25'), startdate=start, enddate=None)
            self.holding_set.create(security_id='USD Cash', qty=Decimal('97.15'), startdate=start, enddate=None)
    
class Client(models.Model):
    username = models.CharField(max_length=100, primary_key=True)
    refresh_token = models.CharField(max_length=100)
    access_token = models.CharField(max_length=100, null=True, blank=True)
    api_server = models.CharField(max_length=100, null=True, blank=True)
    token_expiry = models.DateTimeField(null=True, blank=True)
    authorization_lock = threading.Lock()

    @classmethod 
    def CreateClient(cls, username, refresh_token):
        client = Client(username = username, refresh_token = refresh_token)
        client.Authorize()
        client.SyncAccounts()
        return client
    
    @classmethod 
    def Get(cls, username):
        client = Client.objects.get(username=username)
        client.Authorize()
        return client

    def __str__(self):
        return self.username

    def __enter__(self):
        self.Authorize()
        return self

    def __exit__(self, type, value, traceback):
        self.CloseSession()     
        
    @property
    def needs_refresh(self):
        if not self.token_expiry: return True
        if not self.access_token: return True
        return self.token_expiry < (timezone.now() - datetime.timedelta(seconds = 10))
    
    def Authorize(self):
        assert self.refresh_token, "We don't have a refresh_token at all! How did that happen?"

        with self.authorization_lock:
            if self.needs_refresh:
                _URL_LOGIN = 'https://login.questrade.com/oauth2/token?grant_type=refresh_token&refresh_token='
                r = requests.get(_URL_LOGIN + self.refresh_token)
                r.raise_for_status()
                json = r.json()
                self.api_server = json['api_server'] + 'v1/'
                self.refresh_token = json['refresh_token']
                self.access_token = json['access_token']
                self.token_expiry = timezone.now() + datetime.timedelta(seconds = json['expires_in'])
                # Make sure to save out to DB
                self.save()

        self.session = requests.Session()
        self.session.headers.update({'Authorization': 'Bearer' + ' ' + self.access_token})

          
        
    def CloseSession(self):
        self.session.close()

    def _GetRequest(self, url, params={}):
        r = self.session.get(self.api_server + url, params=params)
        r.raise_for_status()
        return r.json()

    def SyncAccounts(self):
        json = self._GetRequest('accounts')
        for a in json['accounts']:
            Account.objects.update_or_create(type=json['type'], account_id=json['number'], client=self)
            
    def UpdateMarketPrices(self):
        symbols = Holding.current.filter(account__client=self, security__type=Security.Type.Stock).values_list('security__symbol', flat=True).distinct()
        securities = Security.stocks.filter(symbol__in=symbols)
        json = self._GetRequest('markets/quotes', 'ids=' + ','.join([str(s.symbolid) for s in securities if s.symbolid > 0]))
        for q in json['quotes']:
            price = q['lastTradePriceTrHrs']
            if not price: price = q['lastTradePrice']   
            if not price: 
                print('No price available for {}... zeroing out.', q['symbol'])
                price = 100
            stock = Security.stocks.get(symbol=q['symbol'])
            stock.livePrice = Decimal(str(price))
            stock.save()

        r = requests.get('https://openexchangerates.org/api/latest.json', params={'app_id':'eb324bcd04b743c2830360072d84e024', 'symbols':'CAD'})
        price = Decimal(str(r.json()['rates']['CAD']))
        Currency.objects.filter(code='USD').update(livePrice=price)
                            
    def _GetActivities(self, account_id, startTime, endTime):
        json = self._GetRequest('accounts/{}/activities'.format(account_id), {'startTime': startTime.isoformat(), 'endTime': endTime.isoformat()})
        logger.debug(json)
        return json['activities']

    def _FindSymbolId(self, symbol):
        json = self._GetRequest('symbols/search', {'prefix':symbol})
        for s in json['symbols']:
            if s['isTradable'] and symbol == s['symbol']: 
                logger.debug("Matching {} to {}".format(symbol, s))
                return s['symbolId']
        return 0

    def _GetSecurityInfoList(self, symbolids):
        if len(symbolids) == 0:
            return []
        if len(symbolids) == 1:
            json = self._GetRequest('symbols/{}'.format(','.join(map(str,symbolids))))
        else:     
            json = self._GetRequest('symbols', 'ids='+','.join(map(str,symbolids)))
        logger.debug(json)
        return json['symbols']
    
    def SyncActivities(self, startDate='2011-02-01'):
        for account in self.accounts.all():
            print ('Syncing all activities for {}: '.format(account), end='')
            start = account.GetMostRecentActivityDate()
            if start: start = arrow.get(start).shift(days=+1)
            else: start = arrow.get(startDate)
            
            date_range = arrow.Arrow.interval('day', start, arrow.now(), 30)
            print('{} requests'.format(len(date_range)), end='')
            for start, end in date_range:
                print('.',end='',flush=True)
                logger.debug(account.id, start, end)
                activities_list = self._GetActivities(account.id, start, end.replace(hour=0, minute=0, second=0))
                for json in activities_list: 
                    ActivityJson.Add(json, account)
            print()

    def UpdateSecurityInfo(self):
        with transaction.atomic():
            for stock in Security.stocks.all():
                if stock.symbolid == 0:
                    print('finding {}'.format(stock))
                    stock.symbolid = self._FindSymbolId(stock.symbol)
                    
                    print('finding {}'.format(stock.symbolid))
                    stock.save()

    def SyncCurrentAccountBalances(self):
        for a in self.accounts.all():
            json = self._GetRequest('accounts/%s/balances'%(a.id))           
            a.curBalanceSynced = next(currency['totalEquity'] for currency in json['combinedBalances'] if currency['currency'] == 'CAD')
            a.sodBalanceSynced = next(currency['totalEquity'] for currency in json['sodCombinedBalances'] if currency['currency'] == 'CAD')
            a.save()


def DoWork():
    DataProvider.Init()
    for a in Account.objects.all():
        a.RegenerateActivities()
        a.RegenerateHoldings()
    DataProvider.SyncAllSecurities()

def All():
    Currency.objects.all().delete()
    for c in Client.objects.all():
        c.Authorize()
        c.SyncActivities()
    DoWork()
