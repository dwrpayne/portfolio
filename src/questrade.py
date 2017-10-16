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

sys.path.append(os.path.join(os.path.dirname(__file__), '.'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from utils import as_currency, strdate
from dataprovider import DataProvider

#logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

data_provider = DataProvider.Create()
data_provider.SyncExchangeRates('USD', '2000-01-01')

class Position:
    def __init__(self, symbol, currency, qty=0, marketprice=0, bookprice=0):
        self.symbol = symbol
        self.currency = currency
        self.qty = qty
        self.marketprice = marketprice
        self.bookprice = bookprice
        
        # TODO: track base price from actual init day of position in Canadian currency
        self.bookpriceCAD = bookprice

    @classmethod
    def FromJson(self, json):
        position = Position(json['symbol'], 'CAD' if '.TO' in json['symbol'] else 'USD', json['openQuantity'], json['currentPrice'], json['averageEntryPrice'])
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

class Activity:
    def __init__(self, json):
        self.tradeDate = arrow.get(json['tradeDate'])
        self.transactionDate = arrow.get(json['transactionDate'])
        self.action = json['action'] # "Buy" or "Sell" or "    "
        self.symbol = json['symbol']
        self.currency = json['currency']
        self.qty = json['quantity'] # 0 if a dividend
        self.price = json['price'] # price if trade, div/share amt
        self.commission = json['commission'] # Always negative
        self.netAmount = json['netAmount']
        self.type = json['type'] # "Trades", "Dividends", "Deposits"
        self.description = json['description']

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
    def __init__(self, date=arrow.now(), positions=[], cashByCurrency = defaultdict(float)):
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
        self.capgains = defaultdict(float)
        self.income = defaultdict(float)
        self.dividends = defaultdict(float)

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
            

class Account:
    def __init__(self, json):
        self.type = json['type']
        self.id = json['number']
        self.activityHistory = []
        self.holdings = {}
        self.currentHoldings = Holdings()
        self.taxData = TaxData()
        
        self.DATA_FILE = os.path.join(os.path.dirname(__file__), 'private', '{}.pkl'.format(self.id))
        
    def __repr__(self):
        return "Account({},{},{},{})".format(self.id, self.type, self.currentHoldings.cashByCurrency, self.currentHoldings.positions)

    def __str__(self):
        return "Account {} - {}".format(self.id, self.type) + "\n======================================\n" + \
               '\n'.join(map(str, self.GetPositions())) + '\n' + \
               '\n'.join(["{} cash: {}".format(cur, as_currency(cash)) for cur,cash in self.currentHoldings.cashByCurrency.items()]) + '\n' + \
                str(self.taxData) + '\n'

    def Save(self):
        with open(self.DATA_FILE, 'wb') as f:
            pickle.dump(self.activityHistory, f)

    def Load(self):
        if os.path.exists(self.DATA_FILE):
            with open(self.DATA_FILE, 'rb') as f:
                self.activityHistory = pickle.load(f)

    def GetMostRecentActivityDate(self):
        return max([a.tradeDate for a in self.activityHistory], default=None)

    def SetBalance(self, json):
        for currency in json['perCurrencyBalances']:
            self.currentHoldings.cashByCurrency[currency['currency']] = currency['cash']
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


class Client:
    def __init__(self, username, refresh_token=None):        
        self.accounts = []	
        self.username = username     
        self.Authorize(refresh_token)
        self.SyncAccounts()

    def _GetTokenFile(self):
        return os.path.join(os.path.dirname(__file__), 'private', self.username+'.token')
    
    def _LoadToken(self):
        if os.path.exists(self._GetTokenFile()):
            with open(self._GetTokenFile()) as f:
                token = f.read()
                if len(token) > 10: return token
        return None

    def Authorize(self, refresh_token):		
        # Either we init with a token, or we load the previously stored good one.
        refresh_token = refresh_token or self._LoadToken()
        assert refresh_token, "We don't have a refresh_token! The backing file must have been deleted. You need to regenerate a new refresh token."
        _URL_LOGIN = 'https://login.questrade.com/oauth2/token?grant_type=refresh_token&refresh_token='
        r = requests.get(_URL_LOGIN+refresh_token)
        r.raise_for_status()
        j = r.json()
        self.api_server = j['api_server'] + 'v1/'
        refresh_token = j['refresh_token']

        self.session = requests.Session()
        self.session.headers.update({'Authorization': j['token_type'] + ' ' + j['access_token']})

        # Save out the new token we just got.
        with open(self._GetTokenFile(), 'w') as f:
            f.write(refresh_token)

    def _GetRequest(self, url, params={}):
        r = self.session.get(self.api_server + url, params=params)
        r.raise_for_status()
        return r.json()

    def SyncAccounts(self):
        json = self._GetRequest('accounts')
        self.accounts = [Account(a) for a in json['accounts']]

    def SyncAccountBalances(self):
        print('Syncing account balances for {}...'.format(self.username))
        for account in self.accounts:
            account.SetBalance(self._GetRequest('accounts/%s/balances'%(account.id)))

    def PrintCombinedBalances(self):
        for account in self.accounts:
            delta = account.combinedCAD - account.sodCombinedCAD
            print("{} {}: {} -> {} ({})".format(self.username, account.type, as_currency(account.sodCombinedCAD), as_currency(account.combinedCAD), as_currency(delta)))

    def SyncAccountPositions(self):
        print('Syncing account positions for {}...'.format(self.username))
        for account in self.accounts:
            json = self._GetRequest('accounts/%s/positions'%(account.id))
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
            for account in self.accounts:
                position = account.GetPosition(q['symbol'])
                if position: position.marketprice = price

    def GetPositions(self):
        return [p for a in self.accounts for p in a.GetPositions()]

    def PrintPositions(self, collapse=False):
        if collapse:
            positions = self.GetPositions()
            for symbol in {p.symbol for p in positions}:
                print(sum([p for p in positions if p.symbol==symbol]))
        else:
            for account in self.accounts:      
                print (account)
            
    def _GetActivities(self, account_id, startTime, endTime):
        params = {}
        params['startTime'] = startTime.isoformat()
        params['endTime'] = endTime.isoformat()

        json = self._GetRequest('accounts/%s/activities'%(account_id), {'startTime': startTime.isoformat(), 'endTime': endTime.isoformat()})
        logger.debug(json)
        return [Activity(a) for a in json['activities']]

    def SyncAllActivitiesSlow(self, startDate):
        print ('Syncing all activities for {}...'.format(self.username))
        for account in self.accounts:
            account.Load()

            start = account.GetMostRecentActivityDate()
            if start: start = start.shift(days=+1)
            else: start = arrow.get(startDate)
            
            date_range = arrow.Arrow.interval('day', start, arrow.now(), 30)
            num_requests = len(date_range)
            
            activities = []
            for start, end in date_range:
                activities += self._GetActivities(account.id, start, end.replace(hour=0, minute=0, second=0)) 

            for symbol in {activity.symbol for activity in activities}:
                if symbol:
                    data_provider.SyncPrices(symbol, startDate)
            for activity in activities:
                activity.UpdatePriceData()
                account.AddActivity(activity)

            account.Save()

            account.ProcessActivityHistory()

    def GenerateHoldingsHistory(self):        
        for account in self.accounts:
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


def HackInitMyAccount(account):
    if account.id == '51407958': # David TFSA
        account.currentHoldings.positions.append(Position('AGNC', 'USD', 70, marketprice=29.45, bookprice=29.301))
        account.currentHoldings.positions.append(Position('VBK', 'USD', 34, marketprice=64.3, bookprice=61.151))
        account.currentHoldings.positions.append(Position('VUG', 'USD', 118, marketprice=83.64, bookprice=53.79))
        account.currentHoldings.cashByCurrency['CAD'] = 92.30
        account.currentHoldings.cashByCurrency['USD'] = 163.62
    if account.id == '51424829': # David RRSP
        account.currentHoldings.positions.append(Position('EA', 'USD', 300, marketprice=18.06, bookprice=11))
        account.currentHoldings.positions.append(Position('VOT', 'USD', 120, marketprice=66.4, bookprice=47.83))
        account.currentHoldings.positions.append(Position('VWO', 'USD', 220, marketprice=46.41, bookprice=42.0))
        account.currentHoldings.positions.append(Position('XBB.TO', 'CAD', 260, marketprice=28.73, bookprice=28.83))
        account.currentHoldings.positions.append(Position('XIU.TO', 'CAD', 200, marketprice=20.45, bookprice=16.83))
        account.currentHoldings.cashByCurrency['CAD'] = 0
        account.currentHoldings.cashByCurrency['USD'] = -118.3
    if account.id == '51419220': # Sarah TFSA
        account.currentHoldings.positions.append(Position('VBR', 'USD', 90, marketprice=70.42, bookprice=56.43))
        account.currentHoldings.positions.append(Position('XBB.TO', 'CAD', 85, marketprice=28.73, bookprice=29.262))
        account.currentHoldings.positions.append(Position('XIN.TO', 'CAD', 140, marketprice=19.1, bookprice=18.482))
        account.currentHoldings.cashByCurrency['CAD'] = 147.25
        account.currentHoldings.cashByCurrency['USD'] = 97.15
    




def GetFullClientData(client_name):
    c = Client(client_name)
    for a in c.accounts: 
        HackInitMyAccount(a)
        if len(a.GetPositions()) > 0: 
            a.holdings[start] = Holdings(arrow.get(start), a.GetPositions(), a.currentHoldings.cashByCurrency)

    c.SyncAllActivitiesSlow(start)

    #c.GenerateHoldingsHistory()
    c.UpdateMarketPrices()
    
#for a in c.accounts: 
   #     print (a)
    return c

start = '2011-02-01'

david = GetFullClientData('David')
sarah = GetFullClientData('Sarah')
all_accounts = david.accounts + sarah.accounts

#raw_data = [d + "," + ','.join([str(a.GetAllHoldings()[d].GetTotalValue() if d in a.GetAllHoldings() else 0) for a in all_accounts]) for d in sorted(list(all_accounts[0].GetAllHoldings().keys()))]
#print ('date, ' + ','.join([a.type for a in all_accounts]))
#print ('\n'.join(raw_data))

positions = david.GetPositions() + sarah.GetPositions()
for p in positions: data_provider.SyncPrices(p.symbol, start)

print ('\nSymbol\tPrice\t\t   Change\t\tShares\tGain')
total_gain = 0
total_value = 0
for symbol in ['VBR', 'VTI', 'VUN.TO', 'VXUS', 'VCN.TO', 'VAB.TO', 'VDU.TO', 'TSLA']:
    total_pos = sum([p for p in positions if p.symbol==symbol])
    yesterday_price = data_provider.GetPrice(symbol, strdate(arrow.now().shift(days=-1)))
    price_delta = total_pos.marketprice-yesterday_price
    this_gain = price_delta * total_pos.qty * data_provider.GetExchangeRate(total_pos.currency, strdate(arrow.now()))
    total_gain += this_gain
    total_value += total_pos.GetMarketValueCAD()
    print("{} \t{:.2f}\t\t{:+.2f} ({:+.2%})\t\t{}  \t{}".format(symbol.split('.')[0], total_pos.marketprice, price_delta, price_delta / yesterday_price, total_pos.qty, as_currency(this_gain)))
print('-------------------------------------')
print('Total: \t\t\t{:+,.2f}({:+.2%})\t{}'.format(total_gain, total_gain / total_value, as_currency(total_value)))
print('\nCurrent USD exchange: {:.4f}'.format( 1/data_provider.GetExchangeRate('USD', strdate(arrow.now()))))
    
#c.SyncAllActivitiesSlow(start)
#c.PrintPositions()

#c = Client('Sarah')
#c.SyncAccountPositions()
#c.SyncAccountBalances()
#c.PrintPositions()