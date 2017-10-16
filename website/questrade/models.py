from django.db import models
from django.utils import timezone
import requests
import pickle
import os
import sys
import operator
import arrow
from collections import defaultdict
import logging 
import progressbar
import pickle
import copy
import datetime
from decimal import Decimal

from pandas_datareader import data as pdr
from fix_yahoo_finance import pdr_override
pdr_override()

sys.path.append(os.path.join(os.path.dirname(__file__), '.'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from utils import as_currency, strdate

#logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StockPrice(models.Model):
    symbol = models.CharField(max_length=100, unique_for_date="date")
    date = models.DateField(default=datetime.date.today)
    value = models.DecimalField(max_digits=16, decimal_places=6)

    class Meta:
        unique_together = ('symbol', 'date')

    def __str__(self):
        return "{} {} {}".format(self.symbol, self.date, self.value)

class ExchangeRate(models.Model):
    basecurrency = models.CharField(max_length=100)
    currency = models.CharField(max_length=100)
    date = models.DateField(default=datetime.date.today)
    value = models.DecimalField(max_digits=16, decimal_places=6)
    class Meta:
        unique_together = ('basecurrency', 'currency', 'date')

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
                df = pdr.DataReader(symbol, 'yahoo', start_date, end_date)
                StockPrice.objects.bulk_create([
                    StockPrice(symbol=symbol, date=date, value=price) 
                    for date, price in zip(df.index, df['Close'])
                    ])
                print('DONE!')
                break
            except Exception as e:
                print (e)
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
                df = pdr.DataReader(symbol, 'fred', start_date, end_date)                
                ExchangeRate.objects.bulk_create([
                    ExchangeRate(basecurrency=self.base_currency, currency=currency, date=date, value=price) 
                    for date, price in zip(df.index, df[symbol])
                    ])
                print('DONE!')
                break
            except Exception as e:
                print (e)
                print ('Failed, retrying!')
                pass    

    def GetPrice(self, symbol, date):
        if symbol == 'DLR.U.TO': return 10       
        return StockPrice.objects.filter(symbol=symbol, date__lte=date, value__gt=0).order_by('-date')[0].value
    
    def GetExchangeRate(self, currency, date):
        if currency == self.base_currency: return 1
        return ExchangeRate.objects.filter(basecurrency=self.base_currency, currency=currency, date__lte=date, value__gt=0).order_by('-date')[0].value

    
data_provider = DataProvider()


class Position:
    def __init__(self, symbol, currency, qty=0, marketprice=0, bookprice=0):
        self.symbol = symbol
        self.currency = currency
        self.qty = qty
        self.marketprice = Decimal(marketprice)
        self.bookprice = Decimal(bookprice)
        
        # TODO: track base price from actual init day of position in Canadian currency
        self.bookpriceCAD = Decimal(bookprice)

    @classmethod
    def FromJson(self, json):
        position = Position(json['symbol'], 'CAD' if '.TO' in json['symbol'] else 'USD', json['openQuantity'], 
                            Decimal(str(json['currentPrice'])), Decimal(str(json['averageEntryPrice'])))
        return position

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
        
    def __radd__(self, other):
        return Position(self.symbol, self.currency, self.qty, self.marketprice, self.bookprice)

    def __add__(self, other):
        total_qty = self.qty + other.qty
        return Position(self.symbol, self.currency, total_qty, self.marketprice, (self.GetBookValue() + other.GetBookValue())/total_qty)

    def __repr__(self):
        return "Position({},{},{},{})".format(self.symbol, self.qty, self.marketprice, self.bookprice)

    def __str__(self):
        return "{}, {} @ {}: {} -> {} ({}) {}".format(self.symbol, self.qty, self.marketprice, as_currency(self.GetBookValue()), as_currency(self.GetMarketValue()), as_currency(self.GetPNL()), self.currency)

    def GetMarketValue(self):
        return self.marketprice * self.qty

    def GetMarketValueCAD(self):
        return self.marketprice * self.qty * data_provider.GetExchangeRate(self.currency, strdate(arrow.now()))

    def GetBookValue(self):
        return self.bookprice * self.qty

    def GetBookValueCAD(self):
        return self.bookpriceCAD * self.qty

    def GetPNL(self):
        return self.GetMarketValue() - self.GetBookValue()

class Activity(models.Model):
    tradeDate = models.DateField()
    transactionDate = models.DateField()
    action = models.CharField(max_length=100)
    symbol = models.CharField(max_length=100)
    currency = models.CharField(max_length=100)
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    value = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    commission = models.DecimalField(max_digits=16, decimal_places=6)
    netAmount = models.DecimalField(max_digits=16, decimal_places=6)
    type = models.CharField(max_length=100)
    description = models.CharField(max_length=1000)

    @classmethod
    def CreateFromJson(cls, json):
        activity = Activity(
            tradeDate = arrow.get(json['tradeDate'])
            ,transactionDate = arrow.get(json['transactionDate'])
            ,action = json['action'] # "Buy" or "Sell" or "    "
            ,symbol = json['symbol']
            ,currency = json['currency']
            ,qty = Decimal(str(json['quantity'])) # 0 if a dividend
            ,price = Decimal(str(json['price'])) # price if trade, div/share amt
            ,commission = Decimal(str(json['commission'])) # Always negative
            ,netAmount = Decimal(str(json['netAmount']))
            ,type = json['type'] # "Trades", "Dividends", "Deposits"
            ,description = json['description']
            )
        return activity

        # Type          Action
        # Trades                ["Buy", "Sell"]
        # Dividends             "" or "DIV"
        # Deposits              "DEP" for taxable, or "CON" for RRSP/TFSA, or "CSP" for SRRSP
        # Fees and rebates      "FCH"
        # FX conversion         "FXT" this has currency + netAmount pos/neg

        # In sell trade, qty is negative, price and net amount are both positive.
        # 

    def __str__(self):
        return "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}".format(self.tradeDate.format(), self.action, self.symbol, self.currency,self.qty, self.price, self.commission, self.netAmount, self.type, self.description)

    def __repr__(self):
        return "Activity({},{},{},{},{},{},{},{},{},{})".format(self.tradeDate, self.action, self.symbol, self.currency,self.qty, self.price, self.commission, self.netAmount, self.type, self.description)

    def UpdatePriceData(self):        
        if self.price == 0 and self.symbol:   
            self.price = data_provider.GetPrice(self.symbol, strdate(self.tradeDate))

class Holdings:
    def __init__(self, date=arrow.now(), positions=[], cashByCurrency = defaultdict(Decimal)):
        self.strdate = strdate(date)
        self.positions = copy.deepcopy(positions)
        self.cashByCurrency = copy.deepcopy(cashByCurrency)
        pass
                
    def __repr__(self):
        return "Holdings({},{},{})".format(self.strdate, self.positions, self.cashByCurrency)

    def __str__(self):
        return "Total value as of as of {}: {}".format(self.strdate, as_currency(self.GetTotalValue()))
    
    def GetTotalValue(self):
        total = sum([p.GetMarketValue() * data_provider.GetExchangeRate(p.currency, self.strdate) for p in self.positions])
        total += sum([val * data_provider.GetExchangeRate(currency, self.strdate) for currency, val in self.cashByCurrency.items()])
        return total

    def UpdateMarketPrices(self):
        for p in self.positions:
            price = data_provider.GetPrice(p.symbol, self.strdate)
            p.marketprice = price

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
            

class Account(models.Model):
    client = models.ForeignKey('Client', on_delete=models.CASCADE)
    type = models.CharField(max_length=100)
    account_id = models.IntegerField(default=0, primary_key = True)
       
    @classmethod 
    def CreateAccountFromJson(cls, json, client):
        account = Account(type=json['type'], account_id=json['number'], client=client)
        account.activityHistory = []
        account.holdings = {}
        account.currentHoldings = Holdings()
        account.taxData = TaxData()        
        account.DATA_FILE = os.path.join(os.path.dirname(__file__), 'private', '{}.pkl'.format(account.account_id))
        account.save()
        return account

    @classmethod
    def from_db(cls, db, field_name, values):
        instance = super().from_db(db, field_name, values)
        instance.activityHistory = []
        instance.holdings = {}
        instance.currentHoldings = Holdings()
        instance.taxData = TaxData()        
        instance.DATA_FILE = os.path.join(os.path.dirname(__file__), 'private', '{}.pkl'.format(instance.account_id))
        return instance
        
    def __repr__(self):
        return "Account({},{},{})".format(self.client, self.account_id, self.type)

    def __str__(self):
        if not hasattr(self, 'currentHoldings'):
            return "Account {} {} - {}".format(self.client, self.account_id, self.type)
        return "Account {} - {}".format(self.account_id, self.type) + "\n======================================\n" + \
               '\n'.join(map(str, self.GetPositions())) + '\n' + \
               '\n'.join(["{} cash: {}".format(cur, as_currency(cash)) for cur,cash in self.currentHoldings.cashByCurrency.items()]) + '\n' + \
                str(self.taxData) + '\n'

    def Save(self):
        with open(self.DATA_FILE, 'wb') as f:
            pickle.dump(self.activityHistory, f)

    def Load(self):
        try:
            if os.path.exists(self.DATA_FILE):
                with open(self.DATA_FILE, 'rb') as f:
                    self.activityHistory = pickle.load(f)
        except:
            pass

    def GetMostRecentActivityDate(self):
        return max([a.tradeDate for a in self.activityHistory], default=None)

    def SetBalance(self, json):
        for currency in json['perCurrencyBalances']:
            self.currentHoldings.cashByCurrency[currency['currency']] = Decimal(str(currency['cash']))
        self.combinedCAD = next(currency['totalEquity'] for currency in json['combinedBalances'] if currency['currency'] == 'CAD')
        self.sodCombinedCAD = next(currency['totalEquity'] for currency in json['sodCombinedBalances'] if currency['currency'] == 'CAD')

    def GetTotalCAD(self):
        return self.balance.combinedCAD

    def GetTotalSod(self):
        return self.balance.sodCombinedCAD

    def SetPositions(self, positions):
        self.currentHoldings.positions = positions

    def GetPosition(self, symbol, create=True):
        matches = [p for p in self.currentHoldings.positions if p.symbol==symbol]
        if len(matches) == 1: return matches[0]
        return None

    def GetPositions(self, include_closed=False):
        return sorted([p for p in self.currentHoldings.positions if include_closed or p.qty > 0], key=operator.attrgetter('symbol'))

    def GetAllHoldings(self):
        return self.holdings

    def AddCash(self, currency, amt):
        self.currentHoldings.cashByCurrency[currency] += amt

    def AddActivity(self, activity):
        self.activityHistory.append(activity)

    def ProcessActivityHistory(self):
        for a in sorted(self.activityHistory, key=operator.attrgetter('tradeDate')):
            logger.debug("Adding... {}".format(a))
            self.ProcessActivity(a)
            logger.debug(repr(self))

            holdings = Holdings(a.tradeDate, self.currentHoldings.positions, self.currentHoldings.cashByCurrency)
            self.holdings[holdings.strdate] = holdings
           
            logger.debug(repr(holdings))

    def ProcessActivity(self, activity):
        assert_msg = 'Unhandled type: Account is {} and activity is {}'.format(self, activity)

        position = None

        # Hack to skip calls/options - just track cash effect
        if 'CALL ' in activity.description or 'PUT ' in activity.description: 
            self.AddCash(activity.currency, activity.netAmount)
            return

        # Hack to fix invalid Questrade data just for me
        if 'ISHARES S&P/TSX 60 INDEX' in activity.description: activity.symbol = 'XIU.TO'
        elif 'VANGUARD GROWTH ETF' in activity.description: activity.symbol = 'VUG'
        elif 'SMALLCAP GROWTH ETF' in activity.description: activity.symbol = 'VBK'
        elif 'SMALL-CAP VALUE ETF' in activity.description: activity.symbol = 'VBR'
        elif 'ISHARES MSCI EAFE INDEX' in activity.description: activity.symbol = 'XIN.TO'
        elif 'AMERICAN CAPITAL AGENCY CORP' in activity.description: activity.symbol = 'AGNC'
        elif 'MSCI JAPAN INDEX FD' in activity.description: activity.symbol = 'EWJ'
        elif 'VANGUARD EMERGING' in activity.description: activity.symbol = 'VWO'
        elif 'VANGUARD MID-CAP GROWTH' in activity.description: activity.symbol = 'VOT'
        elif 'ISHARES DEX SHORT TERM BOND' in activity.description: activity.symbol = 'XBB.TO'
        elif 'ELECTRONIC ARTS INC' in activity.description: activity.symbol = 'EA'
        elif 'WESTJET AIRLINES LTD' in activity.description: activity.symbol = 'WJA.TO'

        if activity.action =='FXT':
            if 'AS OF ' in activity.description:
                activity.tradeDate = arrow.get(activity.description.split('AS OF ')[1].split(' ')[0], 'MM/DD/YY')                

        if activity.symbol:
            position = self.GetPosition(activity.symbol)
            if not position:
                position = Position(activity.symbol, activity.currency)
                self.currentHoldings.positions.append(position)

            
        self.taxData.GatherTaxData(position, activity)

        if activity.type == 'Deposits':
            if self.type == 'TFSA' or self.type == 'RRSP':      assert activity.action == 'CON', assert_msg
            elif self.type == 'SRRSP':                          assert activity.action == 'CSP', assert_msg
            else:                                               assert activity.action == 'DEP', assert_msg

            self.AddCash(activity.currency, activity.netAmount)
            if position:
                position.qty += activity.qty

        elif activity.type == 'Transfers':
            self.AddCash(activity.currency, activity.netAmount)
            
        elif activity.type == 'Withdrawals':
            if position:
                position.qty += activity.qty
            self.AddCash(activity.currency, activity.netAmount)

        elif activity.type == 'Dividends':
            self.AddCash(activity.currency, activity.netAmount)

            if position:
                # Reduce book price of position by dividend amt per share held
                # TODO: Hack for incomplete data
                div_per_share = activity.netAmount / (position.qty if position.qty else 1)

                # TODO: 15% withholding tax on USD stocks?
                position.bookprice -= div_per_share

        elif activity.type == 'Fees and rebates':
            assert activity.action=='FCH', assert_msg
            self.AddCash(activity.currency, activity.netAmount)

        elif activity.type == 'Interest':
            self.AddCash(activity.currency, activity.netAmount)

        elif activity.type == 'FX conversion':
            assert activity.action=='FXT', assert_msg            
            self.AddCash(activity.currency, activity.netAmount)

        elif activity.type == 'Other':
            # BRW means a journalled trade
            assert activity.action == 'BRW', assert_msg
            position.qty += activity.qty

        elif activity.type == 'Trades':
            assert activity.action == 'Buy' or activity.action == 'Sell', assert_msg
                                        
            self.AddCash(activity.currency, activity.netAmount)
            position.Trade(activity.qty, activity.price, activity.commission, strdate(activity.tradeDate))

        elif activity.type == 'Corporate actions':
            # NAC = Name change
            assert activity.action == 'NAC', assert_msg

        else: 
            assert False, assert_msg


class Client(models.Model):
    username = models.CharField(max_length=100, primary_key=True)
    refresh_token = models.CharField(max_length=100)

    @classmethod 
    def CreateClient(cls, username, refresh_token):
        client = Client(username = username, refresh_token = refresh_token)
        client.accounts = list(Account.objects.filter(client=self))
        client.Authorize()
        client.SyncAccounts()
        return client

    def __str__(self):
        return self.username

    @classmethod
    def from_db(cls, db, field_name, values):
        instance = super().from_db(db, field_name, values)
        instance.accounts = list(Account.objects.filter(client=instance))
        return instance

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

    def GetAccounts(self):
        return self.accounts

    def SyncAccounts(self):
        json = self._GetRequest('accounts')
        for a in json['accounts']:
            Account.CreateAccountFromJson(a, self)
        self.accounts = list(Account.objects.filter(client=self))

    def SyncAccountBalances(self):
        print('Syncing account balances for {}...'.format(self.username))
        for account in self.GetAccounts():
            account.SetBalance(self._GetRequest('accounts/%s/balances'%(account.account_id)))

    def PrintCombinedBalances(self):
        for account in self.GetAccounts():
            delta = account.combinedCAD - account.sodCombinedCAD
            print("{} {}: {} -> {} ({})".format(self.username, account.type, as_currency(account.sodCombinedCAD), as_currency(account.combinedCAD), as_currency(delta)))

    def SyncAccountPositions(self):
        print('Syncing account positions for {}...'.format(self.username))
        for account in self.GetAccounts():
            json = self._GetRequest('accounts/%s/positions'%(account.account_id))
            account.SetPositions([Position.FromJson(j) for j in json['positions']])

    def _FindSymbolId(self, symbol):
        json = self._GetRequest('symbols/search', {'prefix':symbol})
        for s in json['symbols']:
            if symbol == s['symbol']: 
                logger.debug("Matching {} to {}".format(symbol, s))
                return str(s['symbolId'])                
        return ''          

    def UpdateMarketPrices(self):
        symbols = {p.symbol for p in self.GetPositions()}
        json = self._GetRequest('markets/quotes', 'ids=' + ','.join(map(self._FindSymbolId, symbols)))
        for q in json['quotes']:
            price = q['lastTradePriceTrHrs']
            if not price: price = q['lastTradePrice']            
            for account in self.GetAccounts():
                position = account.GetPosition(q['symbol'])
                if position: position.marketprice = price

    def GetPositions(self):
        return [p for a in self.GetAccounts() for p in a.GetPositions()]

    def PrintPositions(self, collapse=False):
        if collapse:
            positions = self.GetPositions()
            for symbol in {p.symbol for p in positions}:
                print(sum([p for p in positions if p.symbol==symbol]))
        else:
            for account in self.GetAccounts():      
                print (account)
            
    def _GetActivities(self, account_id, startTime, endTime):
        params = {}
        params['startTime'] = startTime.isoformat()
        params['endTime'] = endTime.isoformat()

        json = self._GetRequest('accounts/%s/activities'%(account_id), {'startTime': startTime.isoformat(), 'endTime': endTime.isoformat()})
        logger.debug(json)
        return [Activity.CreateFromJson(a) for a in json['activities']]

    def SyncAllActivitiesSlow(self, startDate):
        print ('Syncing all activities for {}...'.format(self.username))
        for account in self.GetAccounts():
            account.Load()

            start = account.GetMostRecentActivityDate()
            if start: start = start.shift(days=+1)
            else: start = arrow.get(startDate)
            
            date_range = arrow.Arrow.interval('day', start, arrow.now(), 30)
            num_requests = len(date_range)
            
            activities = []
            for start, end in date_range:
                activities += self._GetActivities(account.account_id, start, end.replace(hour=0, minute=0, second=0)) 

            for symbol in {activity.symbol for activity in activities}:
                if symbol:
                    data_provider.SyncStockPrices(symbol)
            for activity in activities:
                activity.UpdatePriceData()
                account.AddActivity(activity)

            account.Save()

            account.ProcessActivityHistory()

    def GenerateHoldingsHistory(self):        
        for account in self.GetAccounts():
            for p in account.GetPositions(include_closed=True):
                holdings = account.GetAllHoldings()
                for day in arrow.Arrow.range('day', arrow.get(min(holdings)), arrow.now()):
                    if strdate(day) in holdings:
                        last_holding = holdings[strdate(day)]
                        last_holding.UpdateMarketPrices()
                    else: 
                        new_holding = Holdings(day, last_holding.positions, last_holding.cashByCurrency)
                        new_holding.UpdateMarketPrices()
                        holdings[strdate(day)] = new_holding

    def SyncPrices(self, start):
        for p in self.GetPositions():
            data_provider.SyncStockPrices(p.symbol)

    def CloseSession(self):
        self.session.close()


def HackInitMyAccount(account):
    if account.account_id == '51407958': # David TFSA
        account.currentHoldings.positions.append(Position('AGNC', 'USD', 70, marketprice=29.45, bookprice=29.301))
        account.currentHoldings.positions.append(Position('VBK', 'USD', 34, marketprice=64.3, bookprice=61.151))
        account.currentHoldings.positions.append(Position('VUG', 'USD', 118, marketprice=83.64, bookprice=53.79))
        account.currentHoldings.cashByCurrency['CAD'] = Decimal('92.30')
        account.currentHoldings.cashByCurrency['USD'] = Decimal('163.62')
    if account.account_id == '51424829': # David RRSP
        account.currentHoldings.positions.append(Position('EA', 'USD', 300, marketprice=18.06, bookprice=11))
        account.currentHoldings.positions.append(Position('VOT', 'USD', 120, marketprice=66.4, bookprice=47.83))
        account.currentHoldings.positions.append(Position('VWO', 'USD', 220, marketprice=46.41, bookprice=42.0))
        account.currentHoldings.positions.append(Position('XBB.TO', 'CAD', 260, marketprice=28.73, bookprice=28.83))
        account.currentHoldings.positions.append(Position('XIU.TO', 'CAD', 200, marketprice=20.45, bookprice=16.83))
        account.currentHoldings.cashByCurrency['CAD'] = Decimal('0')
        account.currentHoldings.cashByCurrency['USD'] = Decimal('-118.3')
    if account.account_id == '51419220': # Sarah TFSA
        account.currentHoldings.positions.append(Position('VBR', 'USD', 90, marketprice=70.42, bookprice=56.43))
        account.currentHoldings.positions.append(Position('XBB.TO', 'CAD', 85, marketprice=28.73, bookprice=29.262))
        account.currentHoldings.positions.append(Position('XIN.TO', 'CAD', 140, marketprice=19.1, bookprice=18.482))
        account.currentHoldings.cashByCurrency['CAD'] = Decimal('147.25')
        account.currentHoldings.cashByCurrency['USD'] = Decimal('97.15')

# Create your models here.

#class Client(models.Model):
#    username = models.CharField(max_length=100, primary_key=True)
#    refresh_token = models.CharField(max_length=100)

#    def _GetTokenFile(self):
#        return os.path.join(os.path.dirname(__file__), 'private', self.username+'.token')
    
#    def _LoadToken(self):
#        if os.path.exists(self._GetTokenFile()):
#            with open(self._GetTokenFile()) as f:
#                token = f.read()
#                if len(token) > 10: return token
#        return None

#    def Authorize(self, refresh_token):		
#        # Either we init with a token, or we load the previously stored good one.
#        refresh_token = refresh_token or self._LoadToken()
#        assert refresh_token, "We don't have a refresh_token! The backing file must have been deleted. You need to regenerate a new refresh token."
#        _URL_LOGIN = 'https://login.questrade.com/oauth2/token?grant_type=refresh_token&refresh_token='
#        r = requests.get(_URL_LOGIN+refresh_token)
#        r.raise_for_status()
#        j = r.json()
#        self.api_server = j['api_server'] + 'v1/'
#        self.refresh_token = j['refresh_token']
        
#        # Save out the new token we just got.
#        with open(self._GetTokenFile(), 'w') as f:
#            f.write(refresh_token)

#class Account(models.Model):
#    client = models.ForeignKey(Client, on_delete=models.CASCADE)
#    type = models.CharField(max_length=100, primary_key = True)
#    id = models.IntegerField(default=0)