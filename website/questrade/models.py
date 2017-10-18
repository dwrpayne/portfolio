from django.db import models
from django.utils import timezone
from djchoices import DjangoChoices, ChoiceItem

import requests
import pickle
import os
import sys
import operator
import arrow
from collections import defaultdict
import logging 
import pickle
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

    symbolid = models.BigIntegerField(primary_key=True)
    symbol = models.CharField(max_length=100)
    description = models.CharField(max_length=500)
    type = models.CharField(max_length=12, choices=SecurityType.choices)
    exchange = models.CharField(max_length=20)
    currency = models.CharField(max_length=3)
    isQuotable = models.BooleanField()
    isTradable = models.BooleanField()
      
    class Meta:
        verbose_name_plural = 'Securities'
    

class StockPrice(models.Model):
    symbol = models.CharField(max_length=100, unique_for_date="date")
    date = models.DateField(default=datetime.date.today)
    value = models.DecimalField(max_digits=16, decimal_places=6)

    class Meta:
        unique_together = ('symbol', 'date')
        get_latest_by = 'date'
        indexes = [
            models.Index(fields=['symbol', 'date'])
        ]

    def __str__(self):
        return "{} {} {}".format(self.symbol, self.date, self.value)

class ExchangeRate(models.Model):
    basecurrency = models.CharField(max_length=100)
    currency = models.CharField(max_length=100)
    date = models.DateField(default=datetime.date.today)
    value = models.DecimalField(max_digits=16, decimal_places=6)
    class Meta:
        unique_together = ('basecurrency', 'currency', 'date')
        get_latest_by = 'date'
        indexes = [
            models.Index(fields=['basecurrency', 'currency', 'date'])
        ]

    def __str__(self):
        return "{}->{} {} {}".format(self.basecurrency, self.currency,  self.date, self.value)
    

class DataProvider:
    DATA_FILE = os.path.join(os.path.dirname(__file__), 'private', 'datastore.pkl')
    EXCH_RATES_SYMBOL = {('CAD','USD') : 'DEXCAUS'}
    
    def __init__(self, base_currency = 'CAD'):       
        self.base_currency = base_currency
                
    def SyncStockPrices(self, symbol):
        # Hack to remap
        if symbol == 'DLR.U.TO': symbol = 'DLR-U.TO'

        start_date=datetime.date(2000,1,1)
        end_date=datetime.date.today()
        all_prices = StockPrice.objects.filter(symbol=symbol)
        if all_prices.exists():
            start_date = all_prices.latest('date').date + datetime.timedelta(days=1)
        if start_date >= end_date:
            print ('Already synced data for {}, skipping.'.format(symbol))
            return               

        for retry in range(5):
            try:
                print('Syncing prices for {} from {} to {}...'.format(symbol, start_date, end_date), end='')
                df = pdr.DataReader(symbol, 'yahoo', start_date, end_date).fillna(0)
                StockPrice.objects.bulk_create(
                    [StockPrice(symbol=symbol, date=date, value=price) 
                    for date, price in zip(df.index, df['Close']) if date.date() > start_date and price > 0])
                print('DONE!')
                break
            except Exception as e:
                traceback.print_exc()
                print ('Failed, retrying!')
                pass              

    def SyncExchangeRates(self, currency):
        start_date=datetime.date(2000,1,1)
        end_date=datetime.date.today()
        all_prices = ExchangeRate.objects.filter(basecurrency=self.base_currency, currency=currency)
        if all_prices.exists():
            start_date = all_prices.latest('date').date + datetime.timedelta(days=1)
        if start_date >= end_date:
            print ('Already synced data for {}, skipping.'.format(symbol))
            return

        symbol = self.EXCH_RATES_SYMBOL[(self.base_currency,currency)]

        for retry in range(5):
            try:
                print('Syncing prices for {} from {} to {}...'.format(symbol, start_date, end_date), end='')
                df = pdr.DataReader(symbol, 'fred', start_date, end_date).fillna(0)              
                ExchangeRate.objects.bulk_create(
                    [ExchangeRate(basecurrency=self.base_currency, currency=currency, date=date, value=price) 
                    for date, price in zip(df.index, df[symbol]) if date.date() > start_date and price > 0])
                print('DONE!')
                break
            except Exception as e:
                print (e)
                print ('Failed, retrying!')
                pass    

    def GetPrice(self, symbol, date):
        if symbol == 'DLR.U.TO': return 10    
        if symbol in ['CAD', 'USD']: return 1
        try:
            return StockPrice.objects.filter(symbol=symbol, date__lte=date, value__gt=0).order_by('-date')[0].value
        except Exception as e:
            print ("Couldn't get stock price for {} on {}".format(symbol, date))
            traceback.print_exc()
            return 0
    
    def GetExchangeRate(self, currency, date):
        if currency == self.base_currency: return 1
        return ExchangeRate.objects.filter(basecurrency=self.base_currency, currency=currency, date__lte=date, value__gt=0).order_by('-date')[0].value

    
data_provider = DataProvider()

class Position:
    def Trade(self, qty, price, commission, trade_date):
        exch = data_provider.GetExchangeRate(self.currency, trade_date)
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
           
class Holding(models.Model):
    account = models.ForeignKey('Account', on_delete=models.CASCADE, db_index=True)
    symbol = models.CharField(max_length=20) #models.ForeignKey(Security, on_delete=models.CASCADE)
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    startdate = models.DateField()
    enddate = models.DateField(null=True)

    class Meta:
        unique_together = ('account', 'symbol', 'startdate')
        get_latest_by = 'startdate'
        ordering = ['startdate']

    def __repr__(self):
        return "Holding({},{},{},{},{})".format(self.account, self.symbol, self.qty, self.startdate, self.enddate)
    

class Activity(models.Model):
    account = models.ForeignKey('Account', on_delete=models.CASCADE, db_index=True)
    tradeDate = models.DateField()
    transactionDate = models.DateField()
    action = models.CharField(max_length=100)
    symbol = models.CharField(max_length=100)
    currency = models.CharField(max_length=100)
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    commission = models.DecimalField(max_digits=16, decimal_places=2)
    netAmount = models.DecimalField(max_digits=16, decimal_places=2)
    type = models.CharField(max_length=100)
    description = models.CharField(max_length=1000)
    
    class Meta:
        unique_together = ('account', 'tradeDate', 'action', 'symbol', 'currency', 'qty', 'price', 'netAmount', 'type', 'description')
        verbose_name_plural = 'Activities'
        get_latest_by = 'tradeDate'
        ordering = ['tradeDate']

    @classmethod
    def CreateFromJson(cls, json, account):
        price = json['price']
        symbol = json['symbol']
        tradeDate = arrow.get(json['tradeDate']).date()
        if price == 0 and symbol:   
            price = data_provider.GetPrice(symbol, strdate(tradeDate))

        Activity.objects.get_or_create(
            account = account
            ,tradeDate = tradeDate
            ,transactionDate = arrow.get(json['transactionDate']).date()
            ,action = json['action'] # "Buy" or "Sell" or "    "
            ,symbol = symbol
            ,currency = json['currency']
            ,qty = Decimal(str(json['quantity'])) # 0 if a dividend
            ,price = Decimal(str(price)) # price if trade, div/share amt
            ,commission = Decimal(str(json['commission'])) # Always negative
            ,netAmount = Decimal(str(json['netAmount']))
            ,type = json['type'] # "Trades", "Dividends", "Deposits"
            ,description = json['description']
            )

        #if not created:
        #    print("Warning: tried to create duplicate activity from json {}\nThere was already a DB entry: {}".format(json, obj))

        # Type          Action
        # Trades                ["Buy", "Sell"]
        # Dividends             "" or "DIV"
        # Deposits              "DEP" for taxable, or "CON" for RRSP/TFSA, or "CSP" for SRRSP
        # Fees and rebates      "FCH"
        # FX conversion         "FXT" this has currency + netAmount pos/neg

        # In sell trade, qty is negative, price and net amount are both positive.
        # 

    def __str__(self):
        return "{} - {} - {}\t{}\t{}\t{}\t{}\t{}".format(self.account, self.tradeDate, self.symbol, self.action, self.qty, self.price, self.type, self.description)

    def __repr__(self):
        return "Activity({},{},{},{},{},{},{},{},{},{})".format(self.tradeDate, self.action, self.symbol, self.currency,self.qty, self.price, self.commission, self.netAmount, self.type, self.description)
    
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
               assert self.symbol, assert_msg
            else:
                assert False, assert_msg
        elif self.type == 'Trades':
            # TODO: Hack to handle options
            if not self.symbol and not 'CALL ' in self.description and not 'PUT ' in self.description: 
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

        if self.action =='FXT':
            if 'AS OF ' in self.description:
                asof_date = arrow.get(self.description.split('AS OF ')[1].split(' ')[0], 'MM/DD/YY').date()
                print("FXT Transaction at {} (asof date: {}). Timedelta is {}".format(self.tradeDate, asof_date, self.tradeDate-asof_date))
                if (self.tradeDate-asof_date).days > 365:
                    asof_date = asof_date.replace(year=asof_date.year+1)
                self.tradeDate = asof_date
        
        self.Validate()

    # Returns a dict {currency:amount, symbol:amount, ...}
    def GetHoldingEffect(self):
        effect = defaultdict(Decimal)
        # TODO: Hack to skip calls/options - just track cash effect
        if 'CALL ' in self.description or 'PUT ' in self.description: 
            effect[self.currency] = self.netAmount
            return

        if self.type in ['Deposits', 'Withdrawals', 'Trades']:
            effect[self.currency] = self.netAmount
            if self.symbol:
                effect[self.symbol] = self.qty

        elif self.type in ['Transfers', 'Dividends', 'Fees and rebates', 'Interest', 'FX conversion']:
            effect[self.currency] = self.netAmount
            
        elif self.type == 'Other':
            # activity BRW means a journalled trade
            effect[self.symbol] = self.qty
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
        self.activity_set.latest().tradeDate
            
    def RegenerateDBHoldings(self):
        Holding.objects.filter(account=self).delete()
        for activity in self.activity_set:
            activity.Preprocess()
            
            # TODO: switch this hacky cash/symbol equivalence to a proper stock table foreign key. "CAD" shouldn't be a symbol
            for symbol, amount in activity.GetHoldingEffect().items():
                # TODO: this should be a "manager method"
                queryset = Holding.objects.filter(account=self, symbol=symbol)
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

                Holding.objects.create(account=self, symbol=symbol, qty=previous_amount+amount, startdate=activity.tradeDate, enddate=None)

    def GetValueAtDate(self, date):
        print(date)
        holdings_query = Holding.objects.filter(account=self, startdate__lte=date).exclude(enddate__lt=date).exclude(qty=0)
        if not holdings_query.exists(): return 0
        cash = sum(holdings_query.filter(symbol__in=['CAD', 'USD']).values_list('qty', flat=True))
        holdings_query = holdings_query.exclude(symbol='CAD').exclude(symbol='USD')
        if not holdings_query.exists(): return cash

        qtys = holdings_query.values_list('symbol', 'qty')
        total = cash
        for symbol in holdings_query.values_list('symbol', flat=True):
            qty = holdings_query.get(symbol=symbol).qty
            val = StockPrice.objects.filter(symbol=symbol, date__lte=date).latest().value
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
            
    def _FindSymbolId(self, symbol):
        json = self._GetRequest('symbols/search', {'prefix':symbol})
        for s in json['symbols']:
            if symbol == s['symbol']: 
                logger.debug("Matching {} to {}".format(symbol, s))
                return str(s['symbolId'])                
        return ''    

    def GetMarketPrice(self, symbol):
        json = self._GetRequest('markets/quotes', 'ids=' + symbol)
        for q in json['quotes']:
            price = q['lastTradePriceTrHrs']
            if not price: price = q['lastTradePrice']
            return price	

    def UpdateMarketPrices(self):
        symbols = Holding.objects.filter(account__in=self.account_set.all()).values_list('symbol', flat=True)
        json = self._GetRequest('markets/quotes', 'ids=' + ','.join(map(self._FindSymbolId, symbols)))
        for q in json['quotes']:
            price = q['lastTradePriceTrHrs']
            if not price: price = q['lastTradePrice']            
            for account in self.account_set.all():
                pass
                #TODO: Implement this correctly.... how is this going to work? Temp flag or "closed" flag in the stockprices table?
                            
    def _GetActivities(self, account_id, startTime, endTime):
        params = {}
        params['startTime'] = startTime.isoformat()
        params['endTime'] = endTime.isoformat()

        json = self._GetRequest('accounts/%s/activities'%(account_id), {'startTime': startTime.isoformat(), 'endTime': endTime.isoformat()})
        logger.debug(json)
        return json['activities']

    def SyncAllActivitiesSlow(self, startDate):
        print ('Syncing all activities for {}...'.format(self.username))
        for account in self.account_set.all():
            start = account.GetMostRecentActivityDate()
            if start: start = arrow.get(start).shift(days=+1)
            else: start = arrow.get(startDate)
            
            date_range = arrow.Arrow.interval('day', start, arrow.now(), 30)
            num_requests = len(date_range)
            
            for start, end in date_range:
                print (account.account_id, start, end)
                for a_json in self._GetActivities(account.account_id, start, end.replace(hour=0, minute=0, second=0)):
                    #print("Creating " + str(a_json))
                    a = Activity.CreateFromJson(a_json, account)

            account.LoadHistoryFromDB()

    def SyncPrices(self, start):
        for symbol in Holding.objects.filter(account__in=self.account_set.all()).values_list('symbol', flat=True):
            data_provider.SyncStockPrices(symbol)

    def CloseSession(self):
        self.session.close()

def HackInitMyAccount():
    start = '2011-01-01'
    Holding.objects.all().delete()
    Holding.objects.bulk_create([
        Holding(account=Account.objects.get(account_id=51407958), symbol='AGNC', qty=70, startdate=start, enddate=None),
        Holding(account=Account.objects.get(account_id=51407958), symbol='VBK', qty=34, startdate=start, enddate=None),
        Holding(account=Account.objects.get(account_id=51407958), symbol='VUG', qty=118, startdate=start, enddate=None),
        Holding(account=Account.objects.get(account_id=51407958), symbol='CAD', qty=Decimal('92.30'), startdate=start, enddate=None),
        Holding(account=Account.objects.get(account_id=51407958), symbol='USD', qty=Decimal('163.62'), startdate=start, enddate=None),

        Holding(account=Account.objects.get(account_id=51424829), symbol='EA', qty=300, startdate=start, enddate=None),
        Holding(account=Account.objects.get(account_id=51424829), symbol='VOT', qty=120, startdate=start, enddate=None),
        Holding(account=Account.objects.get(account_id=51424829), symbol='VWO', qty=220, startdate=start, enddate=None),
        Holding(account=Account.objects.get(account_id=51424829), symbol='XBB.TO', qty=260, startdate=start, enddate=None),
        Holding(account=Account.objects.get(account_id=51424829), symbol='XIU.TO', qty=200, startdate=start, enddate=None),
        Holding(account=Account.objects.get(account_id=51424829), symbol='CAD', qty=Decimal('0'), startdate=start, enddate=None),
        Holding(account=Account.objects.get(account_id=51424829), symbol='USD', qty=Decimal('-118.3'), startdate=start, enddate=None),

        Holding(account=Account.objects.get(account_id=51419220), symbol='VBR', qty=90, startdate=start, enddate=None),
        Holding(account=Account.objects.get(account_id=51419220), symbol='XBB.TO', qty=85, startdate=start, enddate=None),
        Holding(account=Account.objects.get(account_id=51419220), symbol='XIN.TO', qty=140, startdate=start, enddate=None),
        Holding(account=Account.objects.get(account_id=51419220), symbol='CAD', qty=Decimal('147.25'), startdate=start, enddate=None),
        Holding(account=Account.objects.get(account_id=51419220), symbol='USD', qty=Decimal('97.15'), startdate=start, enddate=None)
    ])
    