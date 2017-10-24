from django.db import models
from django.db.utils import IntegrityError
from django.utils import timezone
from django.db.models import F, Max
from djchoices import DjangoChoices, ChoiceItem

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

import pandas
from pandas_datareader import data as pdr
import fix_yahoo_finance as yf
yf.pdr_override()

sys.path.append(os.path.join(os.path.dirname(__file__), '.'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils import as_currency, strdate


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

class Security(models.Model):
    class Type(DjangoChoices):
        Stock = ChoiceItem()
        Option = ChoiceItem()

    symbolid = models.BigIntegerField(default=0)
    symbol = models.CharField(max_length=100, primary_key=True)
    description = models.CharField(max_length=500, default='')
    type = models.CharField(max_length=12, choices=Type.choices, default=Type.Stock)
    listingExchange = models.CharField(max_length=20, default='')
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE)
    prevDayClosePrice = models.DecimalField(max_digits=10, decimal_places=2, default=0)    

    objects = models.Manager()
    stocks = StockSecurityManager()

    @classmethod
    def CreateFromJson(cls, json):
        Security.objects.update_or_create(
            symbolid = json['symbolId']
            , symbol = json['symbol']
            , description = json['description']
            , type = json['securityType']
            , listingExchange = json['listingExchange']
            , currency_id = json['currency']
            , prevDayClosePrice = Decimal(str(json['prevDayClosePrice'])) if json['prevDayClosePrice'] else 0
            )
      
    class Meta:
        verbose_name_plural = 'Securities' 

    def GetLatestEntry(self):
        try:
            return self.securityprice_set.latest().day
        except SecurityPrice.DoesNotExist:
            return datetime.date(2000,1,1)

    def GetPrice(self, day):
        return self.securityprice_set.get(day=day).price

    def GetPriceCAD(self, day):
        return self.GetPrice(day) * self.currency.exchangerate_set.get(day=day).price

    def __str__(self):
        return self.symbol

    def __repr(self):
        return "Security({} {} ({}) {} {})".format(self.symbol, self.symbolid, self.currency, self.listingExchange, self.description)   

class SecurityPrice(models.Model):
    security = models.ForeignKey(Security, on_delete=models.CASCADE)
    day = models.DateField(default=datetime.date.today)
    price = models.DecimalField(max_digits=16, decimal_places=2)

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
    FAKED_VALS = {'DLR.U.TO' : 10., 'CADBASE': 1.}
             
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
                ix = pandas.DatetimeIndex(start=df.index[0], end=end_date, freq='D')
                df.reindex(ix).ffill().fillna(method='pad')
                return [(date, price) for date, price in zip(df.index, df[column]) if date.date() > start_date and price > 0]
            except Exception as e:
                print (e)
                print ('Failed, retrying!')
     
    @classmethod
    def SyncStockPrices(cls, security):
        data = cls._RetrieveData(security.symbol, 'yahoo', security.GetLatestEntry() + datetime.timedelta(days=1))
        security.securityprice_set.bulk_create([SecurityPrice(security=security, day=day, price=price) for day, price in data])

    @classmethod
    def SyncExchangeRates(cls, currency):
        latest = datetime.date(2000,1,1)
        try:
            latest = ExchangeRate.objects.filter(currency=currency).latest().day
        except ExchangeRate.DoesNotExist:
            pass
        data = cls._RetrieveData(currency.rateLookup, 'fred', latest + datetime.timedelta(days=1))
        ExchangeRate.objects.bulk_create([ExchangeRate(currency=currency, day=day, price=price) for day, price in data])

    @classmethod
    def SyncAllSecurities(cls):
        for currency in Currency.objects.all():
            cls.SyncExchangeRates(currency)
        for stock in Security.stocks.all():
            cls.SyncStockPrices(stock)
            
    options = {s:0 for s in Security.objects.filter(type='Option').values_list('symbol', flat=True) }
    @classmethod
    def GetAllPricesCAD(cls, day):
        cash = {s:p for s,p in Currency.objects.filter(exchangerate__day=day).
                values_list('code', 'exchangerate__price') }

        stocks = {s:p for s,p in Security.stocks.filter(securityprice__day=day).
                filter(currency__exchangerate__day=day).
                annotate(price=F('securityprice__price')*F('currency__exchangerate__price')).
                values_list('symbol', 'price') }
        
        return {**cash, **stocks, **cls.options}

class Activity(models.Model):
    account = models.ForeignKey('Account', on_delete=models.CASCADE)
    tradeDate = models.DateField()
    transactionDate = models.DateField()
    settlementDate = models.DateField()
    action = models.CharField(max_length=100)
    security = models.ForeignKey(Security, on_delete=models.CASCADE, null=True)
    description = models.CharField(max_length=1000)
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE)
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    grossAmount = models.DecimalField(max_digits=16, decimal_places=2)
    commission = models.DecimalField(max_digits=16, decimal_places=2)
    netAmount = models.DecimalField(max_digits=16, decimal_places=2)
    type = models.CharField(max_length=100)
    sourcejson = models.CharField(max_length=1000)
    
    class Meta:
        unique_together = ('account', 'tradeDate', 'action', 'security', 'currency', 'qty', 'price', 'netAmount', 'type', 'description')
        verbose_name_plural = 'Activities'
        get_latest_by = 'tradeDate'
        ordering = ['tradeDate']
    
    @classmethod
    def ApplyQuestradeFixes(cls, json):

        # Handle Options cleanup
        if json['description'].startswith('CALL ') or json['description'].startswith('PUT '):
            type, symbol, expiry, strike = json['description'].split()[:4]
            symbol = symbol.strip('.7')
            expiry = datetime.datetime.strptime(expiry, '%m/%d/%y').strftime('%y%m%d')
            optionsymbol = "{:<6}{}{}{:0>8}".format(symbol, expiry, type[0], Decimal(strike)*1000)
            json['symbol'] = optionsymbol

        # Hack to fix invalid Questrade data just for me   
        if json['type'] == 'Trades' and not json['symbolId'] and not json['symbol']:
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

        if json['action'] =='FXT':
            if 'AS OF ' in json['description']:
                tradeDate = arrow.get(json['tradeDate']).date()

                asof_date = arrow.get(json['description'].split('AS OF ')[1].split(' ')[0], 'MM/DD/YY').date()
                print("FXT Transaction at {} (asof date: {}). Timedelta is {}".format(tradeDate, asof_date, tradeDate-asof_date))
                if (tradeDate-asof_date).days > 365:
                    asof_date = asof_date.replace(year=asof_date.year+1)
                json['tradeDate'] = asof_date.isoformat()
                        
        if json['currency'] == json['symbol']:
            json['symbol'] = None

    @classmethod
    def AllowDuplicate(cls, json):        
        # Hack to support actual duplicate transactions (no disambiguation available)
        if json['tradeDate'] == datetime.date(2012,8,17) and json['security_id'] == 'EWJ   130119C00010000':
            return True      
        return False

    @classmethod
    def CreateFromJson(cls, json, account):              
        create_args = {'account' : account, 'currency_id': json['currency'], 
                       'qty': Decimal(str(json['quantity'])), 'sourcejson':str(json)}
        for item in ['tradeDate', 'transactionDate', 'settlementDate']:
            create_args[item] = parser.parse(json[item])
        for item in ['action', 'description', 'type']:
            create_args[item] = json[item]
        for item in ['price', 'grossAmount', 'commission', 'netAmount']:
            create_args[item] = Decimal(str(json[item])) if json[item] else 0

        if json['symbol']: 
            create_args['security_id'] = json['symbol']
        else:
            create_args['security'] = None

        activity, created = Activity.objects.update_or_create(**create_args)
        if not created and cls.AllowDuplicate(json):
            create_args['description'] = create_args['description'] + 'NUM2'
            Activity.objects.create(**create_args)

        activity.Validate()

        return activity

    def __str__(self):
        return "{} - {} - {}\t{}\t{}\t{}\t{}\t{}".format(self.account, self.tradeDate, self.security, self.action, self.qty, self.price, self.type, self.description)

    def __repr__(self):
        return "Activity({},{},{},{},{},{},{},{},{},{})".format(self.tradeDate, self.action, self.security, self.currency,self.qty, self.price, self.commission, self.netAmount, self.type, self.description)
    
    def Validate(self):
        assert self.security or self.currency

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
        """Generates a dict {currency:amount, symbol:amount, ...}"""
        effect = defaultdict(Decimal)

        # Trades affect both currency and stock.
        if self.type in ['Trades']:
            effect[self.currency] = self.netAmount
            effect[self.security] = self.qty

        # Can affect either stock or currency, but not both.
        if self.type in ['Deposits', 'Withdrawals']:
            if self.security:
                effect[self.security] = self.qty
            else:
                effect[self.currency] = self.netAmount

        elif self.type in ['Transfers', 'Dividends', 'Fees and rebates', 'Interest', 'FX conversion']:
            effect[self.currency] = self.netAmount
            
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

    def add_effect(self, account, symbol, qty_delta, date):                       
        previous_qty = 0
        try:
            if self.filter(symbol=symbol, startdate=date, enddate=None).update(qty=F('qty')+qty_delta): return

            current_holding = self.get(symbol=symbol, enddate=None)
            current_holding.enddate = date - datetime.timedelta(days=1)
            previous_qty = current_holding.qty
            current_holding.save(update_fields=['enddate'])

        except Holding.MultipleObjectsReturned:
            print("HoldingManager.add_effect() returned multiple holdings for query {} {} {}".format(symbol))
        except Holding.DoesNotExist:
            pass

        new_qty = previous_qty+qty_delta
        if new_qty:
            print ("Creating {} {} {} {}".format(symbol, previous_qty+qty_delta, date, None))
            self.create(account=account,symbol=symbol, qty=previous_qty+qty_delta, startdate=date, enddate=None)


class CurrentHoldingManager(HoldingManager):
    def get_queryset(self):
        return super().filter(enddate=None)

from django.contrib.contenttypes.models import ContentType

class Holding(models.Model):
    account = models.ForeignKey('Account', on_delete=models.CASCADE)
    symbol = models.CharField(max_length=10, default='')
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    startdate = models.DateField()
    enddate = models.DateField(null=True)
    
    objects = HoldingManager()
    current = CurrentHoldingManager()

    class Meta:
        unique_together = ('account', 'symbol', 'startdate')
        get_latest_by = 'startdate'

    def __repr__(self):
        return "Holding({},{},{},{},{})".format(self.account, self.symbol, self.qty, self.startdate, self.enddate)

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
            for symbol, qty_delta in activity.GetHoldingEffect().items():
                self.holding_set.add_effect(self, symbol, qty_delta, activity.tradeDate)

    def GetValueAtDate(self, date):
        prices = DataProvider.GetAllPricesCAD(date)
        return sum([qty * prices[symbol] for qty, symbol in self.holding_set.at_date(date).values_list('qty', 'symbol')])

        
    def HackInitMyAccount(self):
        start = '2011-01-01'
        if self.id == 51407958:
            self.holding_set.create(symbol='AGNC', qty=70, startdate=start, enddate=None)
            self.holding_set.create(symbol='VBK', qty=34, startdate=start, enddate=None)
            self.holding_set.create(symbol='VUG', qty=118, startdate=start, enddate=None)
            self.holding_set.create(symbol='CAD', qty=Decimal('92.30'), startdate=start, enddate=None)
            self.holding_set.create(symbol='USD', qty=Decimal('163.62'), startdate=start, enddate=None)

        if self.id == 51424829:     
            self.holding_set.create(symbol='EA', qty=300, startdate=start, enddate=None)
            self.holding_set.create(symbol='VOT', qty=120, startdate=start, enddate=None)
            self.holding_set.create(symbol='VWO', qty=220, startdate=start, enddate=None)
            self.holding_set.create(symbol='XBB.TO', qty=260, startdate=start, enddate=None)
            self.holding_set.create(symbol='XIU.TO', qty=200, startdate=start, enddate=None)
            self.holding_set.create(symbol='CAD', qty=Decimal('0'), startdate=start, enddate=None)
            self.holding_set.create(symbol='USD', qty=Decimal('-118.3'), startdate=start, enddate=None)

        if self.id == 51419220:     
            self.holding_set.create(symbol='VBR', qty=90, startdate=start, enddate=None)
            self.holding_set.create(symbol='XBB.TO', qty=85, startdate=start, enddate=None)
            self.holding_set.create(symbol='XIN.TO', qty=140, startdate=start, enddate=None)
            self.holding_set.create(symbol='CAD', qty=Decimal('147.25'), startdate=start, enddate=None)
            self.holding_set.create(symbol='USD', qty=Decimal('97.15'), startdate=start, enddate=None)
    

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
            
    def GetMarketPrice(self, symbol):
        json = self._GetRequest('markets/quotes', 'ids=' + symbol)
        for q in json['quotes']:
            price = q['lastTradePriceTrHrs']
            if not price: price = q['lastTradePrice']
            return price	

    def UpdateMarketPrices(self):
        securities = Holding.objects.filter(account__in=self.account_set.all()).values_list('security', flat=True).distinct()
        json = self._GetRequest('markets/quotes', 'ids=' + ','.join([s.symbolid for s in securities if s.symbolid > 0]))
        for q in json['quotes']:
            price = q['lastTradePriceTrHrs']
            if not price: price = q['lastTradePrice']   
            SecurityPrice.objects.update_or_create(security_symbol = q['symbol'], date=datetime.date.today(), price = Decimal(str(price)))
                            
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

    def EnsureSecuritiesExist(self, symboldata):
        have_symbols = Security.objects.filter(symbol__in=[s for s,i in symboldata]).values_list('symbol', flat=True)

        missing_ids = {id for symbol,id in symboldata if id > 0 and not symbol in have_symbols}
        for security_json in self._GetSecurityInfoList(missing_ids):
            Security.CreateFromJson(security_json)

        for symbol,id in symboldata:
            if symbol and not id:
                related = Security.objects.filter(symbol__startswith=symbol[:3])[0]
                Security.objects.update_or_create(symbol=symbol, type=Security.Type.Option, currency=related.currency)
                                
    def SyncActivities(self, startDate='2011-02-01'):
        for account in self.account_set.all():
            print ('Syncing all activities for {}...'.format(account))
            start = account.GetMostRecentActivityDate()
            if start: start = arrow.get(start).shift(days=+1)
            else: start = arrow.get(startDate)
            
            date_range = arrow.Arrow.interval('day', start, arrow.now(), 30)
            num_requests = len(date_range)
            
            for start, end in date_range:
                logger.debug(account.id, start, end)
                activities_list = self._GetActivities(account.id, start, end.replace(hour=0, minute=0, second=0))
                for json in activities_list: 
                    Activity.ApplyQuestradeFixes(json)
                    if json['symbol'] and not json['symbolId']:
                        json['symbolId'] = self._FindSymbolId(json['symbol'])

                self.EnsureSecuritiesExist({(json['symbol'], json['symbolId']) for json in activities_list})
                for json in activities_list:                    
                    Activity.CreateFromJson(json, account)

    def CloseSession(self):
        self.session.close()
