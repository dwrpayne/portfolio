from django.db import models
from django.utils import timezone
from djchoices import DjangoChoices, ChoiceItem

import requests
import os
import sys
import operator
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

class Security(models.Model):
    class SecurityType(DjangoChoices):
        Stock = ChoiceItem()
        Option = ChoiceItem()
        Bond = ChoiceItem()
        Right = ChoiceItem()
        Gold = ChoiceItem()
        MutualFund = ChoiceItem()
        Index = ChoiceItem()
        Currency = ChoiceItem()

    symbolid = models.BigIntegerField(primary_key=True)
    symbol = models.CharField(max_length=100)
    description = models.CharField(max_length=500)
    securityType = models.CharField(max_length=12, choices=SecurityType.choices)
    listingExchange = models.CharField(max_length=20)
    currency = models.CharField(max_length=3)
    prevDayClosePrice = models.DecimalField(max_digits=10, decimal_places=2)

    @classmethod
    def CreateFromJson(cls, json):
        Security.objects.update_or_create(
            symbolid = json['symbolId']
            , symbol = json['symbol']
            , description = json['description']
            , securityType = json['securityType']
            , listingExchange = json['listingExchange']
            , currency = json['currency']
            , prevDayClosePrice = Decimal(str(json['prevDayClosePrice'])) if json['prevDayClosePrice'] else 0
            )
      
    class Meta:
        verbose_name_plural = 'Securities' 

    def __str__(self):
        return "{} {} {}".format(self.symbol, self.description, self.listingExchange, self.currency)   

class SecurityPriceQuerySet(models.QuerySet):
    def atdate(self, date):
        return self.filter(date__lte=date, price__gt=0).order_by('-date','security__symbol')
        
class SecurityPrice(models.Model):
    security = models.ForeignKey(Security, on_delete=models.CASCADE)
    date = models.DateField(default=datetime.date.today)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    objects = SecurityPriceQuerySet.as_manager()

    class Meta:
        unique_together = ('security', 'date')
        get_latest_by = 'date'
        indexes = [
            models.Index(fields=['security', 'date'])
        ]

    def __str__(self):
        return "{} {} {}".format(self.security, self.date, self.price)

class DataProvider:
    REMAP = {'USD' : 'DEXCAUS',
             'DLR.U.TO' : 'DLR-U.TO'}
             
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
                return []  

    @classmethod
    def _GetLatestEntry(cls, security):
        date = datetime.date(2000,1,1)
        all_prices = SecurityPrice.objects.filter(security=security)
        if all_prices.exists():
            date = all_prices.latest().date + datetime.timedelta(days=1)
        return date
    
    @classmethod
    def SyncStockPrices(cls, security):
        data = cls._RetrieveData(security.symbol, 'yahoo', cls._GetLatestEntry(security))
        SecurityPrice.objects.bulk_create([SecurityPrice(security=security, date=date, price=price) for date, price in data])

    @classmethod
    def SyncExchangeRates(cls, security):
        if security.symbol == 'CAD': return
        data = cls._RetrieveData(security.description, 'fred', cls._GetLatestEntry(security))
        SecurityPrice.objects.bulk_create([SecurityPrice(security=security, date=date, price=price) for date, price in data])

    @classmethod
    def GetPrice(cls, security, date):
        if security.symbol == 'DLR.U.TO': return 10    
        if security.symbol in ['CAD']: return 1
        try:
            return SecurityPrice.objects.filter(security=security, date__lte=date, price__gt=0).order_by('-date')[0].price
        except Exception as e:
            print ("Couldn't get stock price for {} on {}".format(symbol, date))
            traceback.print_exc()
            return None

    @classmethod
    def GetExchangeRate(cls, currency, date):
        return cls.GetPrice(currency, date)

    @classmethod
    def SyncAllSecurities(cls):
        for security in Security.objects.all():
            if security.securityType == Security.SecurityType.Currency:
                cls.SyncExchangeRates(security)
            else:
                cls.SyncStockPrices(security)

class Position:
    def Trade(self, qty, price, commission, trade_date):
        exch = 1
        trade_cost = qty * price + commission
        new_qty = self.qty + qty

        if qty > 0:
            # ACB only changes when you buy, not when you sell.
            self.bookprice = (self.GetBookValue() + (trade_cost)) / new_qty if new_qty else 0
            self.bookpriceCAD = (self.GetBookValueCAD() + (trade_cost * exch)) / new_qty  if new_qty else 0

        self.marketprice = price
        self.qty = new_qty
        
class TaxData:
    def __init__(self):
        self.capgains = defaultdict(Decimal)
        self.income = defaultdict(Decimal)
        self.dividends = defaultdict(Decimal)

    def __str__(self):
        s = "Year\tCapGains\tIncome\tDividends\n"
        years = list(self.capgains) + list(self.income) + list(self.dividends)
        if not years: return ""
        for year in range(min(years), max(years)+1):
            s += "{}\t{}\t\t{}\t{}\n".format(year, as_currency(self.capgains[year]), as_currency(self.income[year]), as_currency(self.dividends[year]))
        return s

    def GatherTaxData(self, position, activity):
        if not position: return

        if activity.action == 'Sell' or activity.type == 'Withdrawals':
            capgains = data_provider.GetExchangeRate(position.currency, strdate(activity.tradeDate)) * (activity.price - position.bookprice) * -activity.qty
            self.capgains[activity.tradeDate.year] += capgains
            logging.info("{} - Sold {} {} at {}. Cost basis was {}. Capital gain of {}".format(
                strdate(activity.tradeDate),
                -activity.qty,
                activity.symbol,
                as_currency(activity.price),
                as_currency(position.bookprice),
                as_currency(capgains)
                ))

        if activity.type == 'Dividends':
            div_amt = data_provider.GetExchangeRate(position.currency, strdate(activity.tradeDate)) * activity.netAmount
            logging.info("{} - Dividend of {}".format(strdate(activity.tradeDate), div_amt))
            self.dividends[activity.tradeDate.year] += div_amt

class HoldingManager(models.Manager):
    def at_date(self, date):
        return super().get_queryset().filter(startdate__lte=date).exclude(enddate__lt=date).exclude(qty=0)

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
    symbol = models.CharField(max_length=100)
    security = models.ForeignKey(Security, on_delete=models.CASCADE, null=True)
    description = models.CharField(max_length=1000)
    currency = models.CharField(max_length=100)
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    grossAmount = models.DecimalField(max_digits=16, decimal_places=2)
    commission = models.DecimalField(max_digits=16, decimal_places=2)
    netAmount = models.DecimalField(max_digits=16, decimal_places=2)
    type = models.CharField(max_length=100)
    cleansed = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ('account', 'tradeDate', 'action', 'security', 'currency', 'qty', 'price', 'netAmount', 'type', 'description')
        verbose_name_plural = 'Activities'
        get_latest_by = 'tradeDate'
        ordering = ['tradeDate']

    @classmethod
    def CreateFromJson(cls, json, account):
        activity, created = Activity.objects.update_or_create(
            account = account
            , tradeDate = arrow.get(json['tradeDate']).date()
            , transactionDate = arrow.get(json['transactionDate']).date()
            , settlementDate = arrow.get(json['settlementDate']).date()
            , action = json['action'] # "Buy" or "Sell" or "    "
            , symbol = json['symbol']
            , security_id = json['symbolId']
            , description = json['description']
            , currency = json['currency']
            , qty = Decimal(str(json['quantity'])) # 0 if a dividend
            , price = Decimal(str(json['price'])) # price if trade, div/share amt
            , grossAmount = Decimal(str(json['grossAmount'])) if json['grossAmount'] else 0
            , commission = Decimal(str(json['commission'])) # Always negative
            , netAmount = Decimal(str(json['netAmount']))
            , type = json['type'] # "Trades", "Dividends", "Deposits"
            )
        if activity.security_id == 0:
            security = None
            activity.save()

        activity.Preprocess()

        # Type          Action
        # Trades                ["Buy", "Sell"]
        # Dividends             "" or "DIV"
        # Deposits              "DEP" for taxable, or "CON" for RRSP/TFSA, or "CSP" for SRRSP
        # Fees and rebates      "FCH"
        # FX conversion         "FXT" this has currency + netAmount pos/neg

        # In sell trade, qty is negative, price and net amount are both positive.
        # 

    def __str__(self):
        return "{} - {} - {}\t{}\t{}\t{}\t{}".format(self.account, self.tradeDate, self.action, self.qty, self.price, self.type, self.description)

    def __repr__(self):
        return "Activity({},{},{},{},{},{},{},{},{})".format(self.tradeDate, self.action, self.currency,self.qty, self.price, self.commission, self.netAmount, self.type, self.description)
    
    def Validate(self):
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
                pass
            # BRW means a journalled trade
            elif self.action == 'BRW':
               assert self.security.symbol, assert_msg
            else:
                assert False, assert_msg
        elif self.type == 'Trades':
            # TODO: Hack to handle options
            if not self.security and not 'CALL ' in self.description and not 'PUT ' in self.description: 
                print('Trade but no position: {}'.format(self))
            assert self.action in ['Buy', 'Sell']        
        elif self.type == 'Corporate actions':
            # NAC = Name change
            assert self.action == 'NAC', assert_msg
        elif self.type in ['Withdrawals', 'Transfers', 'Dividends', 'Interest']:
            pass
        else:
            assert False, assert_msg
            
    def Preprocess(self):
        # Hack to fix invalid Questrade data just for me
        if not self.symbol:
            self.cleansed = True
            if 'ISHARES S&P/TSX 60 INDEX' in self.description: self.symbol = 'XIU.TO'
            elif 'VANGUARD GROWTH ETF' in self.description: self.symbol = 'VUG'
            elif 'SMALLCAP GROWTH ETF' in self.description: self.symbol = 'VBK'
            elif 'SMALL-CAP VALUE ETF' in self.description: self.symbol = 'VBR'
            elif 'ISHARES MSCI EAFE INDEX' in self.description: self.symbol = 'XIN.TO'
            elif 'AMERICAN CAPITAL AGENCY CORP' in self.description: self.symbol = 'AGNC'
            elif 'AMERICAN CAPITAL AGENCY CORP' in self.description: self.symbol = 'AGNC'
            elif 'MSCI JAPAN INDEX FD' in self.description: self.symbol = 'EWJ'
            elif 'VANGUARD EMERGING' in self.description: self.symbol = 'VWO'
            elif 'VANGUARD MID-CAP GROWTH' in self.description: self.symbol = 'VOT'
            elif 'ISHARES DEX SHORT TERM BOND' in self.description: self.symbol = 'XBB.TO'
            elif 'ELECTRONIC ARTS INC' in self.description: self.symbol = 'EA'
            elif 'WESTJET AIRLINES' in self.description: self.symbol = 'WJA.TO'
            else:
                self.cleansed = False;
        if self.cleansed:
            self.security = Security.objects.get(symbol=self.symbol)

        if self.action =='FXT':
            if 'AS OF ' in self.description:
                asof_date = arrow.get(self.description.split('AS OF ')[1].split(' ')[0], 'MM/DD/YY').date()
                print("FXT Transaction at {} (asof date: {}). Timedelta is {}".format(self.tradeDate, asof_date, self.tradeDate-asof_date))
                if (self.tradeDate-asof_date).days > 365:
                    asof_date = asof_date.replace(year=asof_date.year+1)
                self.tradeDate = asof_date
                self.cleansed = True
                
        if self.price == 0 and self.symbol:   
            self.price = DataProvider.GetPrice(self.security, strdate(self.tradeDate))
            self.cleansed = True
        
        self.Validate()
        self.save()

    # Returns a dict {currency:amount, symbol:amount, ...}
    def GetHoldingEffect(self):
        effect = defaultdict(Decimal)
        # TODO: Hack to skip calls/options - just track cash effect
        if 'CALL ' in self.description or 'PUT ' in self.description: 
            effect[self.currency] = self.netAmount
            return effect

        if self.type in ['Deposits', 'Withdrawals', 'Trades']:
            effect[self.currency] = self.netAmount
            if self.security:
                effect[self.security.symbol] = self.qty

        elif self.type in ['Transfers', 'Dividends', 'Fees and rebates', 'Interest', 'FX conversion']:
            effect[self.currency] = self.netAmount
            
        elif self.type == 'Other':
            # activity BRW means a journalled trade
            if self.security:
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
        for activity in self.activity_set.all():
            activity.Preprocess()
        for activity in self.activity_set.all():          
            # TODO: should this return a securityid? or a security?
            for symbol, amount in activity.GetHoldingEffect().items():
                # TODO: this should be a "manager method"
                queryset = Holding.objects.filter(account=self, security__symbol=symbol)
                previous_amount = 0
                if queryset.exists():
                    current_holding = queryset.latest()
                    assert current_holding.enddate is None
                    if current_holding.startdate == activity.tradeDate:
                        current_holding.qty += amount
                        current_holding.save()
                        continue

                    current_holding.enddate = activity.tradeDate - datetime.timedelta(days=1)
                    previous_amount = current_holding.qty
                    current_holding.save()

                print ("Creating {} {} {} {} {}".format(self, symbol, previous_amount+amount, activity.tradeDate, None))
                self.holding_set.create(security__symbol=symbol, qty=previous_amount+amount, startdate=activity.tradeDate, enddate=None)

    def GetValueAtDate(self, date):
        print(date)
        holdings_query = Holding.objects.at_date(date)
        if not holdings_query.exists(): return 0
        cash = sum(holdings_query.filter(security__symbol__in=['CAD', 'USD']).values_list('qty', flat=True))
        holdings_query = holdings_query.exclude(security__symbol='CAD').exclude(security__symbol='USD')
        if not holdings_query.exists(): return cash

        qtys = holdings_query.values_list('security', 'qty')
        total = cash
        for security in holdings_query.values_list('security', flat=True):
            qty = holdings_query.get(security=security).qty
            val = DataProvider.GetPrice(security, date)
            total += qty*val

        return total

class Client(models.Model):
    username = models.CharField(max_length=100, primary_key=True)
    refresh_token = models.CharField(max_length=100)

    @classmethod 
    def CreateClient(cls, username, refresh_token):
        client = Client(username = username, refresh_token = refresh_token)
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
        json = self._GetRequest('markets/quotes', 'ids=' + ','.join([s.symbolid for s in securities]))
        for q in json['quotes']:
            price = q['lastTradePriceTrHrs']
            if not price: price = q['lastTradePrice']   
            SecurityPrice.objects.update_or_create(security_id = q['symbolId'], date=datetime.date.today(), price = Decimal(str(price)))
                            
    def _GetActivities(self, account_id, startTime, endTime):
        params = {}
        params['startTime'] = startTime.isoformat()
        params['endTime'] = endTime.isoformat()

        json = self._GetRequest('accounts/{}/activities'.format(account_id), {'startTime': startTime.isoformat(), 'endTime': endTime.isoformat()})
        logger.debug(json)
        return json['activities']

    def _FindSymbolId(self, symbol):
        json = self._GetRequest('symbols/search', {'prefix':symbol})
        for s in json['symbols']:
            if symbol == s['symbol']: 
                logger.debug("Matching {} to {}".format(symbol, s))
                return str(s['symbolId'])                
        return ''  

    def _GetSecurityInfoList(self, symbolids):
        if len(symbolids) == 0:
            return []
        if len(symbolids) == 1:
            json = self._GetRequest('symbols/{}'.format(','.join(map(str,symbolids))))
        else:     
            json = self._GetRequest('symbols', 'ids='+','.join(map(str,symbolids)))
        logger.debug(json)
        return json['symbols']

    def EnsureSecuritiesExist(self, symbolids):
        print ("Ensuring...{}".format(symbolids))
        have_ids = Security.objects.filter(symbolid__in=symbolids).values_list('symbolid',flat=True)
        missing_ids = {id for id in symbolids if id > 0 and not id in have_ids}
        for security_json in self._GetSecurityInfoList(missing_ids):
            Security.CreateFromJson(security_json)

    def SyncAllActivitiesSlow(self, startDate):
        print ('Syncing all activities for {}...'.format(self.username))
        for account in self.account_set.all():
            start = account.GetMostRecentActivityDate()
            if start: start = arrow.get(start).shift(days=+1)
            else: start = arrow.get(startDate)
            
            date_range = arrow.Arrow.interval('day', start, arrow.now(), 30)
            num_requests = len(date_range)
            
            for start, end in date_range:
                print (account.id, start, end)
                activities_list = self._GetActivities(account.id, start, end.replace(hour=0, minute=0, second=0))
                self.EnsureSecuritiesExist([json['symbolId'] for json in activities_list])
                for json in activities_list:
                    Activity.CreateFromJson(json, account)

    def CloseSession(self):
        self.session.close()

def HackInitMyAccount():
    start = '2011-01-01'
    Holding.objects.all().delete()
    #Holding.objects.bulk_create([
    #    Holding(account=Account.objects.get(account_id=51407958), symbol='AGNC', qty=70, startdate=start, enddate=None),
    #    Holding(account=Account.objects.get(account_id=51407958), symbol='VBK', qty=34, startdate=start, enddate=None),
    #    Holding(account=Account.objects.get(account_id=51407958), symbol='VUG', qty=118, startdate=start, enddate=None),
    #    Holding(account=Account.objects.get(account_id=51407958), symbol='CAD', qty=Decimal('92.30'), startdate=start, enddate=None),
    #    Holding(account=Account.objects.get(account_id=51407958), symbol='USD', qty=Decimal('163.62'), startdate=start, enddate=None),

    #    Holding(account=Account.objects.get(account_id=51424829), symbol='EA', qty=300, startdate=start, enddate=None),
    #    Holding(account=Account.objects.get(account_id=51424829), symbol='VOT', qty=120, startdate=start, enddate=None),
    #    Holding(account=Account.objects.get(account_id=51424829), symbol='VWO', qty=220, startdate=start, enddate=None),
    #    Holding(account=Account.objects.get(account_id=51424829), symbol='XBB.TO', qty=260, startdate=start, enddate=None),
    #    Holding(account=Account.objects.get(account_id=51424829), symbol='XIU.TO', qty=200, startdate=start, enddate=None),
    #    Holding(account=Account.objects.get(account_id=51424829), symbol='CAD', qty=Decimal('0'), startdate=start, enddate=None),
    #    Holding(account=Account.objects.get(account_id=51424829), symbol='USD', qty=Decimal('-118.3'), startdate=start, enddate=None),

    #    Holding(account=Account.objects.get(account_id=51419220), symbol='VBR', qty=90, startdate=start, enddate=None),
    #    Holding(account=Account.objects.get(account_id=51419220), symbol='XBB.TO', qty=85, startdate=start, enddate=None),
    #    Holding(account=Account.objects.get(account_id=51419220), symbol='XIN.TO', qty=140, startdate=start, enddate=None),
    #    Holding(account=Account.objects.get(account_id=51419220), symbol='CAD', qty=Decimal('147.25'), startdate=start, enddate=None),
    #    Holding(account=Account.objects.get(account_id=51419220), symbol='USD', qty=Decimal('97.15'), startdate=start, enddate=None)
    #])
    