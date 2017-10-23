from django.db import models
from django.db.utils import IntegrityError
from django.utils import timezone
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

from pandas_datareader import data as pdr
import fix_yahoo_finance as yf
yf.pdr_override()

sys.path.append(os.path.join(os.path.dirname(__file__), '.'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils import as_currency, strdate


#logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StockSecurityManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.Stock)

class CurrencySecurityManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Security.Type.Currency)
    
class Security(models.Model):
    class Type(DjangoChoices):
        Stock = ChoiceItem()
        Option = ChoiceItem()
        Currency = ChoiceItem()

    symbolid = models.BigIntegerField(default=0)
    symbol = models.CharField(max_length=100, primary_key=True)
    description = models.CharField(max_length=500, default='')
    type = models.CharField(max_length=12, choices=Type.choices, default=Type.Stock)
    listingExchange = models.CharField(max_length=20, default='')
    currency = models.CharField(max_length=3)
    prevDayClosePrice = models.DecimalField(max_digits=10, decimal_places=2, default=0)    

    objects = models.Manager()
    stocks = StockSecurityManager()
    currencies = CurrencySecurityManager()

    @classmethod
    def CreateFromJson(cls, json):
        Security.objects.update_or_create(
            symbolid = json['symbolId']
            , symbol = json['symbol']
            , description = json['description']
            , type = json['securityType']
            , listingExchange = json['listingExchange']
            , currency = json['currency']
            , prevDayClosePrice = Decimal(str(json['prevDayClosePrice'])) if json['prevDayClosePrice'] else 0
            )
      
    class Meta:
        verbose_name_plural = 'Securities' 

    def __str__(self):
        return self.symbol

    def __repr(self):
        return "Security({} {} ({}) {} {})".format(self.symbol, self.symbolid, self.currency, self.listingExchange, self.description)   

class SecurityPriceQuerySet(models.QuerySet):
    def price_at_date(self, date):
        query = self.filter(date__lte=date, price__gt=0)
        if query.exists():
            return self.filter(date__lte=date, price__gt=0).order_by('-date')[0].price
        return 0
        
class SecurityPrice(models.Model):
    security = models.ForeignKey(Security, on_delete=models.CASCADE)
    date = models.DateField(default=datetime.date.today)
    price = models.DecimalField(max_digits=16, decimal_places=2)
    objects = SecurityPriceQuerySet.as_manager()

    class Meta:
        unique_together = ('security', 'date')
        get_latest_by = 'date'
        indexes = [
            models.Index(fields=['security', 'date'])
        ]

    def __str__(self):
        return "{} {} {}".format(self.security, self.date, self.price)

class ExchangeRate(models.Model):
    currency = models.CharField(max_length=3)
    date = models.DateField(default=datetime.date.today)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    class Meta:
        unique_together = ('currency', 'date')
        get_latest_by = 'date'
        indexes = [
            models.Index(fields=['currency', 'date'])
        ]

    def __str__(self):
        return "{} {} {}".format(self.currency, self.date, self.price)


class DataProvider:
    REMAP = {'DLR.U.TO' : 'DLR-U.TO'}
             
    @classmethod
    def _RetrieveData(cls, symbol, source, start_date):
        # Returns a list of tuples (date, price)
        if symbol in cls.REMAP:
            symbol = cls.REMAP[symbol]
        end_date = datetime.date.today()
        if start_date >= end_date:
            print ('Already synced data for {}, skipping.'.format(symbol))
            return []

        column = 'Close' if source == 'yahoo' else symbol
        for retry in range(5):
            try:
                print('Syncing prices for {} from {} to {}...'.format(symbol, start_date, end_date))
                df = pdr.DataReader(symbol, source, start_date, end_date).fillna(0)
                return [(date, price) for date, price in zip(df.index, df[column]) if date.date() > start_date and price > 0]
            except Exception as e:
                print (e)
                print ('Failed, retrying!')

    @classmethod
    def _GetLatestEntry(cls, security):

        date = datetime.date(2010,1,1)
        all_prices = SecurityPrice.objects.filter(security=security)
        if all_prices.exists():
            date = all_prices.latest().date
        return date
    
    @classmethod
    def _GetLatestExchangeRate(cls, currency):
        date = datetime.date(2010,1,1)
        all_prices = ExchangeRate.objects.filter(currency=currency)
        if all_prices.exists():
            date = all_prices.latest().date
        return date
    
    @classmethod
    def SyncStockPrices(cls, security):
        data = cls._RetrieveData(security.symbol, 'yahoo', cls._GetLatestEntry(security) + datetime.timedelta(days=1))
        SecurityPrice.objects.bulk_create([SecurityPrice(security=security, date=date, price=price) for date, price in data])

    @classmethod
    def SyncExchangeRates(cls, security):
        if security.currency == 'CAD': return
        data = cls._RetrieveData(security.description, 'fred', cls._GetLatestExchangeRate(security.currency) + datetime.timedelta(days=1))
        ExchangeRate.objects.bulk_create([ExchangeRate(currency=security.currency, date=date, price=price) for date, price in data])

    @classmethod
    def GetPrice(cls, security, date):
        if security.symbol == 'DLR.U.TO': return 10    
        # Currency type is always worth $1 per unit.
        if security.type == Security.Type.Currency: return 1
        try:
            return SecurityPrice.objects.filter(security=security).price_at_date(date)
        except Exception as e:
            print ("Couldn't get stock price for {} on {}".format(security, date))
            traceback.print_exc()
            return None

    @classmethod
    def GetPriceCAD(cls, security, date):
        return cls.GetPrice(security, date) * cls.GetExchangeRate(security.currency, date)

    @classmethod
    def GetExchangeRate(cls, currency_str, date):
        if currency_str in 'CAD': return 1
        return ExchangeRate.objects.filter(currency=currency_str, date__lte=date, price__gt=0).order_by('-date')[0].price

    @classmethod
    def SyncAllSecurities(cls):
        for currency in Security.currencies.all():
            cls.SyncExchangeRates(currency)
        for stock in Security.stocks.all():
            cls.SyncStockPrices(stock)

class HoldingManager(models.Manager):
    def at_date(self, date):
        return self.get_queryset().filter(startdate__lte=date).exclude(enddate__lt=date).exclude(qty=0)

    def add_effect(self, account, symbol, qty_delta, date):                       
        previous_qty = 0
        try:
            current_holding = self.get(security__symbol=symbol, enddate=None)
            if current_holding.startdate == date:
                current_holding.qty += qty_delta
            else:                        
                current_holding.enddate = date - datetime.timedelta(days=1)
                previous_qty = current_holding.qty
            current_holding.save()
        except Holding.MultipleObjectsReturned:
            print("HoldingManager.add_effect() returned multiple holdings for query {} {} {}".format(symbol, qty_delta, date))
        except Holding.DoesNotExist:
            pass

        print ("Creating {} {} {} {}".format(symbol, previous_qty+qty_delta, date, None))
        self.create(account=account,security_id=symbol, qty=previous_qty+qty_delta, startdate=date, enddate=None)


class CurrentHoldingManager(HoldingManager):
    def get_queryset(self):
        return self.at_date(datetime.date.today())
           
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

class Activity(models.Model):
    account = models.ForeignKey('Account', on_delete=models.CASCADE)
    tradeDate = models.DateField()
    transactionDate = models.DateField()
    settlementDate = models.DateField()
    action = models.CharField(max_length=100)
    security = models.ForeignKey(Security, on_delete=models.CASCADE)
    description = models.CharField(max_length=1000)
    currency = models.CharField(max_length=7)
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

    @classmethod
    def CreateFromJson(cls, json, account):
        # Either we are missing a stock in our init list above, or this is a cash transaction
        if not json['symbol']:
            if not json['type'] in ['Deposits', 'Withdrawals', 'Dividends', 'FX conversion', 'Transfers', 'Fees and rebates', 'Other', 'Interest']:
                print("Transaction didn't get cleaned properly, we don't have a security: Type {} {}".format(json['type'], json['action']))
            assert json['currency'] in ['CAD', 'USD']
            json['symbol'] = json['currency']

        print(json)

        #Hack to adapt to the fact that the symbol for a currency type is hacked to start with "Cash"
        if json['symbol'] == json['currency']:
            json['symbol'] = 'Cash'+json['symbol']
        json['currency'] = 'Cash'+json['currency']

        activity, created = Activity.objects.update_or_create(
            account = account
            , tradeDate = arrow.get(json['tradeDate']).date()
            , transactionDate = arrow.get(json['transactionDate']).date()
            , settlementDate = arrow.get(json['settlementDate']).date()
            , action = json['action'] # "Buy" or "Sell" or "    "
            , security_id = json['symbol']
            , description = json['description']
            , currency = json['currency']
            , qty = Decimal(str(json['quantity'])) # 0 if a dividend
            , price = Decimal(str(json['price'])) # price if trade, div/share amt
            , grossAmount = Decimal(str(json['grossAmount'])) if json['grossAmount'] else 0
            , commission = Decimal(str(json['commission'])) # Always negative
            , netAmount = Decimal(str(json['netAmount']))
            , type = json['type'] # "Trades", "Dividends", "Deposits"
            , sourcejson = str(json)
            )

        activity.Validate()

        return activity

    def __str__(self):
        return "{} - {} - {}\t{}\t{}\t{}\t{}\t{}".format(self.account, self.tradeDate, self.security, self.action, self.qty, self.price, self.type, self.description)

    def __repr__(self):
        return "Activity({},{},{},{},{},{},{},{},{},{})".format(self.tradeDate, self.action, self.security, self.currency,self.qty, self.price, self.commission, self.netAmount, self.type, self.description)
    
    def Validate(self):
        assert self.security, "No security for {}".format(self)

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

        if self.type in ['Deposits', 'Withdrawals', 'Trades']:
            effect[self.currency] = self.netAmount
            if not self.currency == self.security.symbol:
                effect[self.security.symbol] = self.qty

        elif self.type in ['Transfers', 'Dividends', 'Fees and rebates', 'Interest', 'FX conversion']:
            effect[self.currency] = self.netAmount
            
        elif self.type == 'Other':
            # activity BRW means a journalled trade
            if self.action == 'BRW':
                effect[self.security.symbol] = self.qty
            elif self.action == 'EXP':
                effect[self.security.symbol] = self.qty                

        return effect         
            
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
            
    def RegenerateDBHoldings(self):
        Holding.objects.filter(account=self).delete()
        self.HackInitMyAccount()
        for activity in self.activity_set.all():          
            for symbol, qty_delta in activity.GetHoldingEffect().items():
                # TODO: this should be a "manager method"
                # Holding.objects.add_effect(self, symbol, qty_delta, activity.tradeDate)
                previous_qty = 0
                current_holding = self.holding_set.filter(security__symbol=symbol, enddate=None).first()
                if current_holding:
                    if current_holding.startdate == activity.tradeDate:
                        current_holding.qty += qty_delta
                    else:                        
                        current_holding.enddate = activity.tradeDate - datetime.timedelta(days=1)
                        previous_qty = current_holding.qty
                    current_holding.save()

                print ("Creating {} {} {} {} {}".format(self, symbol, previous_qty+qty_delta, activity.tradeDate, None))
                self.holding_set.create(security_id=symbol, qty=previous_qty+qty_delta, startdate=activity.tradeDate, enddate=None)

    def GetValueAtDate(self, date):
        return sum([h.qty * DataProvider.GetPriceCAD(h.security, date) for h in self.holding_set.at_date(date)])

    def GetValuesForDates(self, dates):
        self.holding_set
        
    def HackInitMyAccount(self):
        start = '2011-01-01'
        if self.id == 51407958:
            self.holding_set.create(security_id='AGNC', qty=70, startdate=start, enddate=None)
            self.holding_set.create(security_id='VBK', qty=34, startdate=start, enddate=None)
            self.holding_set.create(security_id='VUG', qty=118, startdate=start, enddate=None)
            self.holding_set.create(security_id='CashCAD', qty=Decimal('92.30'), startdate=start, enddate=None)
            self.holding_set.create(security_id='CashUSD', qty=Decimal('163.62'), startdate=start, enddate=None)

        if self.id == 51424829:     
            self.holding_set.create(security_id='EA', qty=300, startdate=start, enddate=None)
            self.holding_set.create(security_id='VOT', qty=120, startdate=start, enddate=None)
            self.holding_set.create(security_id='VWO', qty=220, startdate=start, enddate=None)
            self.holding_set.create(security_id='XBB.TO', qty=260, startdate=start, enddate=None)
            self.holding_set.create(security_id='XIU.TO', qty=200, startdate=start, enddate=None)
            self.holding_set.create(security_id='CashCAD', qty=Decimal('0'), startdate=start, enddate=None)
            self.holding_set.create(security_id='CashUSD', qty=Decimal('-118.3'), startdate=start, enddate=None)

        if self.id == 51419220:     
            self.holding_set.create(security_id='VBR', qty=90, startdate=start, enddate=None)
            self.holding_set.create(security_id='XBB.TO', qty=85, startdate=start, enddate=None)
            self.holding_set.create(security_id='XIN.TO', qty=140, startdate=start, enddate=None)
            self.holding_set.create(security_id='CashCAD', qty=Decimal('147.25'), startdate=start, enddate=None)
            self.holding_set.create(security_id='CashUSD', qty=Decimal('97.15'), startdate=start, enddate=None)
    

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
            if id == 0:
                related = Security.objects.filter(symbol__startswith=symbol[:3])[0]
                Security.objects.update_or_create(symbol=symbol, type=Security.Type.Option, currency=related.currency)

                
    def SyncAllActivitiesSlow(self, startDate='2011-02-01'):
        for account in self.account_set.all():
            print ('Syncing all activities for {}...'.format(self))
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
