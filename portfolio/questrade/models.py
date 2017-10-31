from django.db import models, transaction
from django.core.exceptions import ObjectDoesNotExist
from django.db.utils import IntegrityError
from django.utils import timezone
from django.db.models import F, Max, Q, Sum
from model_utils import Choices

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

#logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from finance.models import Holding, Security, SecurityPrice, Currency, ExchangeRate, Activity
from finance.models import BaseRawActivity, BaseAccount, BaseClient

class QuestradeRawActivity(BaseRawActivity):
    jsonstr = models.CharField(max_length=1000)
    cleaned = models.CharField(max_length=1000, null=True, blank=True)
    
    class Meta:
        unique_together = ('baserawactivity_ptr', 'jsonstr')
        
    def __str__(self):
        return self.jsonstr
      
    @classmethod
    def AllowDuplicate(cls, s):        
        # Hack to support actual duplicate transactions (no disambiguation available)
        return s == '{"tradeDate": "2012-08-17T00:00:00.000000-04:00", "transactionDate": "2012-08-20T00:00:00.000000-04:00", "settlementDate": "2012-08-20T00:00:00.000000-04:00", "action": "Sell", "symbol": "", "symbolId": 0, "description": "CALL EWJ    01/19/13    10     ISHARES MSCI JAPAN INDEX FD    AS AGENTS, WE HAVE BOUGHT      OR SOLD FOR YOUR ACCOUNT   ", "currency": "USD", "quantity": -5, "price": 0.14, "grossAmount": null, "commission": -14.96, "netAmount": 55.04, "type": "Trades"}'

    @classmethod 
    def Add(cls, json, account):
        s = simplejson.dumps(json)        
        obj, created = QuestradeRawActivity.objects.update_or_create(jsonstr=s, account=account)
        if not created and cls.AllowDuplicate(s):
            s = s.replace('YOUR ACCOUNT   ', 'YOUR ACCOUNT X2')
            QuestradeRawActivity.objects.create(jsonstr=s, account=account)

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
        return Activity.Type.NotImplemented
  
    def GetCleanedJson(self):
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

        json['tradeDate'] = str(parser.parse(json['tradeDate']).date())
        json['type'] = self.GetActivityType(json['type'], json['action'])
        json['qty'] = json['quantity']
        del json['quantity']
                        
        if json['currency'] == json['symbol']:
            json['symbol'] = None
            
        return simplejson.dumps(json)
        
    def CreateActivity(self): 
        json = self.GetCleanedJson()
                
        create_args = {'account' : self.account, 'raw' : self}
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
     

class QuestradeAccount(BaseAccount):
    curBalanceSynced = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    sodBalanceSynced = models.DecimalField(max_digits=19, decimal_places=4, default=0)
            
    def HackInit(self):
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
    
class QuestradeClient(BaseClient):
    refresh_token = models.CharField(max_length=100)
    access_token = models.CharField(max_length=100, null=True, blank=True)
    api_server = models.CharField(max_length=100, null=True, blank=True)
    token_expiry = models.DateTimeField(null=True, blank=True)
    authorization_lock = threading.Lock()

    @classmethod 
    def CreateClient(cls, username, refresh_token):
        client = QuestradeClient(username = username, refresh_token = refresh_token)
        client.Authorize()
        client.SyncAccounts()
        return client
            
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
        for account_json in json['accounts']:
            QuestradeAccount.objects.update_or_create(type=account_json['type'], id=account_json['number'], client=self)
            
    def SyncPrices(self):
        ids = self.currentSecurities.filter(symbolid__gt=0).values_list('symbolid', flat=True)
        json = self._GetRequest('markets/quotes', 'ids=' + ','.join(map(str,ids)))
        for q in json['quotes']:
            price = q['lastTradePriceTrHrs'] or q['lastTradePrice'] or 0
            if not price: 
                print('No price available for {}... zeroing out.', q['symbol'])
            security = Security.stocks.get(symbol=q['symbol'])
            security.live_price = Decimal(str(price))
                            
    def _CreateRawActivities(self, account_id, start, end):
        end = end.replace(hour=0, minute=0, second=0)
        json = self._GetRequest('accounts/{}/activities'.format(account_id), {'startTime': start.isoformat(), 'endTime': endTime.isoformat()})
        logger.debug(json)
        for activity_json in json['activities']:
            QuestradeRawActivity.Add(activity_json, account)

    def _FindSymbolId(self, symbol):
        json = self._GetRequest('symbols/search', {'prefix':symbol})
        for s in json['symbols']:
            if s['isTradable'] and symbol == s['symbol']: 
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
    for a in QuestradeAccount.objects.all():
        a.RegenerateActivities()
        a.RegenerateHoldings()
    DataProvider.SyncAllSecurities()

def All():
    Currency.objects.all().delete()
    for c in QuestradeClient.objects.all():
        c.Authorize()
        c.SyncActivities()
    DoWork()
    
