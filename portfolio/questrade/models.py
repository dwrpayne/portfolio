from django.db import models, transaction
from django.db.utils import IntegrityError
from django.utils import timezone
from django.db.models import F, Max, Q, Sum
from djchoices import DjangoChoices, ChoiceItem
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

import pandas
from pandas_datareader import data as pdr
import fix_yahoo_finance as yf
yf.pdr_override()

#logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Currency(models.Model):
    code = models.CharField(max_length=3, primary_key=True)
    rateLookup = models.CharField(max_length=10)

    def __str__(self):
        return self.code

    class Meta:
        verbose_name_plural = 'Currencies'
        
    def GetExchangeRate(self, day):
        return self.exchangerate_set.get(day=day).price
    
class StockSecurityManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.Stock)

class CashSecurityManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.Cash)

class OptionSecurityManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.Option)

class Security(models.Model):
    Type = Choices('Stock', 'Option', 'Cash')

    symbol = models.CharField(max_length=32, primary_key=True)
    symbolid = models.BigIntegerField(default=0)
    description = models.CharField(max_length=500, default='')
    type = models.CharField(max_length=12, choices=Type, default=Type.Stock)
    listingExchange = models.CharField(max_length=20, default='')
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE)
    lastTradePrice = models.DecimalField(max_digits=16, decimal_places=4, default=0)    

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

    def GetLatestEntry(self):
        try:
            return self.securityprice_set.latest().day
        except SecurityPrice.DoesNotExist:
            return datetime.date(2009,1,1)

    def GetPrice(self, day):
        return self.securityprice_set.get(day=day).price

    def GetPriceCAD(self, day):
        return self.GetPrice(day) * self.currency.exchangerate_set.get(day=day).price

    def __str__(self):
        return "{} {}".format(self.symbol, self.currency)

    def __repr(self):
        return "Security({} {} ({}) {} {})".format(self.symbol, self.symbolid, self.currency, self.listingExchange, self.description)   

class SecurityPrice(models.Model):
    security = models.ForeignKey(Security, on_delete=models.CASCADE)
    day = models.DateField(default=datetime.date.today)
    price = models.DecimalField(max_digits=19, decimal_places=4)

    class Meta:
        unique_together = ('security', 'day')
        get_latest_by = 'day'
        indexes = [
            models.Index(fields=['security', 'day']),
            models.Index(fields=['day'])
        ]

    def __str__(self):
        return "{} {} {}".format(self.security, self.day, self.price)

class ExchangeRate(models.Model):
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE)
    day = models.DateField(default=datetime.date.today)
    price = models.DecimalField(max_digits=16, decimal_places=6)
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
    FAKED_VALS = {'DLR.U.TO':10., 'CADBASE':1., 'USD Cash':1., 'CAD Cash':1.}
    
    @classmethod
    def _RetrieveData(cls, symbol, source, start_date):
        # Returns a list of tuples (day, price)
        end_date = datetime.date.today() - datetime.timedelta(days=1)
        if start_date >= end_date:
            print ('Already synced data for {}, skipping.'.format(symbol))
            return []

        if symbol in cls.FAKED_VALS:
            index = pandas.date_range(start_date, end_date, freq='D').date
            return zip(index, pandas.Series(cls.FAKED_VALS[symbol], index))

        column = 'Close' if source == 'yahoo' else symbol
        for retry in range(5):
            try:
                print('Syncing prices for {} from {} to {}...'.format(symbol, start_date, end_date))
                df = pdr.DataReader(symbol, source, start_date, end_date)
                if df.size == 0:
                    return []
                ix = pandas.DatetimeIndex(start=df.index[0], end=end_date, freq='D')
                df = df.reindex(ix).ffill()
                return zip(ix, df[column])
            except Exception as e:
                print (e)
                print ('Failed, retrying!')
        return []
     
    @classmethod
    def SyncStockPrices(cls, security):
        data = cls._RetrieveData(security.symbol, 'yahoo', security.GetLatestEntry() + datetime.timedelta(days=1))
        security.securityprice_set.bulk_create([SecurityPrice(security=security, day=day, price=price) for day, price in data])

    @classmethod
    def SyncExchangeRates(cls, currency):
        latest = datetime.date(2009,1,1)
        try:
            latest = ExchangeRate.objects.filter(currency=currency).latest().day
        except ExchangeRate.DoesNotExist:
            pass
        data = cls._RetrieveData(currency.rateLookup, 'fred', latest + datetime.timedelta(days=1))
        ExchangeRate.objects.bulk_create([ExchangeRate(currency=currency, day=day, price=price) for day, price in data])

    @classmethod
    def SyncAllSecurities(cls):        
        Currency.objects.update_or_create(code='CAD', rateLookup='CADBASE')
        Currency.objects.update_or_create(code='USD', rateLookup='DEXCAUS')
        for currency in Currency.objects.all():
            Security.objects.update_or_create(symbol=currency.code + ' Cash', currency=currency, type=Security.Type.Cash)
            cls.SyncExchangeRates(currency)
        for stock in Security.stocks.all():
            cls.SyncStockPrices(stock)

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
    def AllowDuplicate(cls, s):        
        # Hack to support actual duplicate transactions (no disambiguation available)
        return s == "{'tradeDate': '2012-08-17T00:00:00.000000-04:00', 'transactionDate': '2012-08-20T00:00:00.000000-04:00', 'settlementDate': '2012-08-20T00:00:00.000000-04:00', 'action': 'Sell', 'symbol': 'EWJ   130119C00010000', 'symbolId': 0, 'description': 'CALL EWJ    01/19/13    10     ISHARES MSCI JAPAN INDEX FD    AS AGENTS, WE HAVE BOUGHT      OR SOLD FOR YOUR ACCOUNT   ', 'currency': 'USD', 'quantity': -5, 'price': 0.14, 'grossAmount': None, 'commission': -14.96, 'netAmount': 55.04, 'type': 'Trades'}"

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
            json['currency'] = 'CAD'

        if json['action'] =='FXT':
            if 'AS OF ' in json['description']:
                tradeDate = arrow.get(json['tradeDate'])

                asof = arrow.get(json['description'].split('AS OF ')[1].split(' ')[0], 'MM/DD/YY')
                #print("FXT Transaction at {} (asof date: {}). Timedelta is {}".format(tradeDate, asof, tradeDate-asof))
                if (tradeDate-asof).days > 365:
                    asof = asof.shift(years=+1)

                json['tradeDate'] = tradeDate.replace(year=asof.year, month=asof.month, day=asof.day).isoformat()
                        
        if json['currency'] == json['symbol']:
            json['symbol'] = None
            
        self.cleaned = simplejson.dumps(json)
        self.save(update_fields=['cleaned'])

class Activity(models.Model):
    account = models.ForeignKey('Account', on_delete=models.CASCADE)
    tradeDate = models.DateField()
    transactionDate = models.DateField()
    settlementDate = models.DateField()
    action = models.CharField(max_length=100)
    security = models.ForeignKey(Security, on_delete=models.CASCADE, null=True, related_name='dontaccess_security')
    description = models.CharField(max_length=1000)
    cash = models.ForeignKey(Security, on_delete=models.CASCADE, null=True, related_name='dontaccess_cash')
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    grossAmount = models.DecimalField(max_digits=16, decimal_places=2)
    commission = models.DecimalField(max_digits=16, decimal_places=2)
    netAmount = models.DecimalField(max_digits=16, decimal_places=2)
    type = models.CharField(max_length=100)
    sourcejson = models.ForeignKey(ActivityJson, on_delete=models.CASCADE)
    
    class Meta:
        unique_together = ('account', 'tradeDate', 'action', 'security', 'cash', 'qty', 'price', 'netAmount', 'type', 'description')
        verbose_name_plural = 'Activities'
        get_latest_by = 'tradeDate'
        ordering = ['tradeDate']
        
    @classmethod
    def CreateFromJson(cls, activityjson): 
        json = simplejson.loads(activityjson.cleaned)

        create_args = {'account' : activityjson.account, 'qty': Decimal(str(json['quantity'])), 'sourcejson' : activityjson}
        for item in ['tradeDate', 'transactionDate', 'settlementDate']:
            create_args[item] = parser.parse(json[item])
        for item in ['action', 'description', 'type']:
            create_args[item] = json[item]
        for item in ['price', 'grossAmount', 'commission', 'netAmount']:
            create_args[item] = Decimal(str(json[item])) 

        if json['symbol']: 
            try:
                type = Security.Type.Stock if len(json['symbol']) < 20 else Security.Type.Option
                security, created = Security.objects.get_or_create(symbol=json['symbol'], currency_id=json['currency'], type=type)
                if created:                    
                    print ("Creating {} {} from activityjson id --> {}".format(json['symbol'], json['currency'], activityjson.id))
                create_args['security'] = security
            except:
                print ("Couldn't create {} {}".format(json['symbol'], json['currency']))
            
        else:
            create_args['security'] = None

        create_args['cash_id'] = json['currency']+' Cash'
            
        activity = Activity(**create_args)
        activity.Validate()
        return activity

    def __str__(self):
        return "{} - {} - {}\t{}\t{}\t{}\t{}\t{}".format(self.account, self.tradeDate, self.security, self.action, self.qty, self.price, self.type, self.description)

    def __repr__(self):
        return "Activity({},{},{},{},{},{},{},{},{},{})".format(self.tradeDate, self.action, self.security, self.cash, self.qty, self.price, self.commission, self.netAmount, self.type, self.description)
    
    def Validate(self):
        assert self.security or self.cash

        assert_msg = 'Unhandled type: {}'.format(self.__dict__)
        if self.type == 'Deposits':
            if self.account.type in ['TFSA', 'RRSP']:      
                assert self.action == 'CON', assert_msg
            elif self.account.type == 'SRRSP':                          
                assert self.action == 'CSP', assert_msg
            else:                                               
                assert self.action == 'DEP', assert_msg
        elif self.type == 'Fees and rebates':
            assert self.action=='FCH', assert_msg
        elif self.type == 'FX conversion':
            assert self.action=='FXT', assert_msg            
        elif self.type == 'Other':
            # Expired option
            if self.action == 'EXP': 
                assert self.security.type == Security.Type.Option
            # BRW means a journalled trade
            elif self.action == 'BRW':
               assert self.security, assert_msg
            else:
                assert False, assert_msg
        elif self.type == 'Trades':
            assert self.action in ['Buy', 'Sell']        
        elif self.type == 'Corporate actions':
            # NAC = Name change
            assert self.action == 'NAC', assert_msg
        elif self.type in ['Withdrawals', 'Transfers', 'Dividends', 'Interest']:
            pass
        else:
            assert False, assert_msg
            
    def GetHoldingEffect(self):
        """Generates a dict {security:amount, ...}"""
        effect = defaultdict(Decimal)

        # Trades affect both cash and stock.
        if self.type in ['Trades', 'Deposits', 'Withdrawals']:
            effect[self.security] = self.qty
            effect[self.cash] = self.netAmount

        elif self.type in ['Transfers', 'Dividends', 'Fees and rebates', 'Interest', 'FX conversion']:
            effect[self.cash] = self.netAmount
            
        elif self.type == 'Other':
            # activity BRW means a journalled trade
            if self.action == 'BRW':
                effect[self.security] = self.qty
            elif self.action == 'EXP':
                effect[self.security] = self.qty

        return effect                     
               
class HoldingManager(models.Manager):
    def at_date(self, date):
        return self.filter(startdate__lte=date).exclude(enddate__lt=date).exclude(qty=0)

    def add_effect(self, account, security, qty_delta, date):                       
        previous_qty = 0
        try:
            if self.filter(security=security, startdate=date, enddate=None).update(qty=F('qty')+qty_delta): return

            current_holding = self.get(security=security, enddate=None)
            current_holding.enddate = date - datetime.timedelta(days=1)
            previous_qty = current_holding.qty
            current_holding.save(update_fields=['enddate'])

        except Holding.MultipleObjectsReturned:
            print("HoldingManager.add_effect() returned multiple holdings for query {} {} {}".format(security))
        except Holding.DoesNotExist:
            pass

        new_qty = previous_qty+qty_delta
        if new_qty:
            print ("Creating {} {} {} {}".format(security, previous_qty+qty_delta, date, None))
            self.create(account=account,security=security, qty=previous_qty+qty_delta, startdate=date, enddate=None)


class CurrentHoldingManager(HoldingManager):
    def get_queryset(self):
        return super().filter(enddate=None)
    
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
    client = models.ForeignKey('Client', on_delete=models.CASCADE)
    type = models.CharField(max_length=100)
    id = models.IntegerField(default=0, primary_key = True)
        
    def __repr__(self):
        return "Account({},{},{})".format(self.client, self.id, self.type)

    def __str__(self):
        return "{} {} {}".format(self.client, self.id, self.type)
    
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

    def GetValueList(self):
        val_list = SecurityPrice.objects.filter(
            Q(security__holding__enddate__gte=F('day'))|Q(security__holding__enddate=None), 
            security__holding__startdate__lte=F('day'),
            security__holding__account_id=self.id, 
            security__currency__exchangerate__day=F('day')
        ).values_list('day').annotate(
            val=Sum(F('price') * F('security__holding__qty') * F('security__currency__exchangerate__price'))
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
        all_activities = [Activity.CreateFromJson(j) for j in self.activityjson_set.all()]
        Activity.objects.bulk_create(all_activities)
        for activityjson in self.activityjson_set.all():
            Activity.CreateFromJson(activityjson)
        
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
            self.holding_set.create(security_id='XBB.TO', qty=260, startdate=start, enddate=None)
            self.holding_set.create(security_id='XIU.TO', qty=200, startdate=start, enddate=None)
            self.holding_set.create(security_id='CAD Cash', qty=Decimal('0'), startdate=start, enddate=None)
            self.holding_set.create(security_id='USD Cash', qty=Decimal('-118.3'), startdate=start, enddate=None)

        if self.id == 51419220:     
            self.holding_set.create(security_id='VBR', qty=90, startdate=start, enddate=None)
            self.holding_set.create(security_id='XBB.TO', qty=85, startdate=start, enddate=None)
            self.holding_set.create(security_id='XIN.TO', qty=140, startdate=start, enddate=None)
            self.holding_set.create(security_id='CAD Cash', qty=Decimal('147.25'), startdate=start, enddate=None)
            self.holding_set.create(security_id='USD Cash', qty=Decimal('97.15'), startdate=start, enddate=None)
    

class Client(models.Model):
    username = models.CharField(max_length=100, primary_key=True)
    refresh_token = models.CharField(max_length=100)

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
        client.SyncAccounts()
        return client

    def __str__(self):
        return self.username
    
    def Authorize(self):		
        assert self.refresh_token, "We don't have a refresh_token at all! How did that happen?"
        _URL_LOGIN = 'https://login.questrade.com/oauth2/token?grant_type=refresh_token&refresh_token='
        r = requests.get(_URL_LOGIN + self.refresh_token)
        r.raise_for_status()
        j = r.json()
        self.api_server = j['api_server'] + 'v1/'
        self.refresh_token = j['refresh_token']

        self.session = requests.Session()
        self.session.headers.update({'Authorization': j['token_type'] + ' ' + j['access_token']})

        # Make sure to save out to DB
        self.save()

    def _GetRequest(self, url, params={}):
        r = self.session.get(self.api_server + url, params=params)
        r.raise_for_status()
        return r.json()

    def SyncAccounts(self):
        json = self._GetRequest('accounts')
        for a in json['accounts']:
            Account.objects.update_or_create(type=json['type'], account_id=json['number'], client=self)
            
    def UpdateMarketPrices(self):
        securities = Holding.current.filter(account__client=self, security__type__=Security.Type.Stock).values_list('security__symbol')
        json = self._GetRequest('markets/quotes', 'ids=' + ','.join([s.symbolid for s in securities if s.symbolid > 0]))
        for q in json['quotes']:
            price = q['lastTradePriceTrHrs']
            if not price: price = q['lastTradePrice']   
            stock = Security.stocks.get(q['symbol'])
            stock.lastTradePrice = Decimal(str(price))
            stock.save()
                            
    def _GetActivities(self, account_id, startTime, endTime):
        json = self._GetRequest('accounts/{}/activities'.format(account_id), {'startTime': startTime.isoformat(), 'endTime': endTime.isoformat()})
        logger.debug(json)
        return json['activities']

    def _FindSymbolId(self, symbol):
        query = Security.objects.filter(symbol=symbol)
        if query: return query[0].symbolid

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
        for account in self.account_set.all():
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

    def CloseSession(self):
        self.session.close()


def DoWork():
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
