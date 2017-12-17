import datetime
import threading
from decimal import Decimal

import arrow
import requests
import simplejson
from dateutil import parser
from django.db import models
from django.utils import timezone

from finance.models import Activity
from finance.models import BaseRawActivity, BaseAccount, BaseClient, ManualRawActivity
from securities.models import Security
from utils.api import api_response

class QuestradeActivityTypeManager(models.Manager):
    def GetActivityType(self, type, action):
        try:
            return QuestradeActivityType.objects.get(q_type=type, q_action=action).activity_type
        except QuestradeActivityType.DoesNotExist:
            print('No action type mapping for "{}" "{}"'.format(type, action))
            return Activity.Type.NotImplemented

class QuestradeActivityType(models.Model):
    q_type = models.CharField(max_length=32)
    q_action = models.CharField(max_length=32)
    activity_type = models.CharField(max_length=32)
    objects = QuestradeActivityTypeManager()

class QuestradeRawActivity(BaseRawActivity):
    jsonstr = models.CharField(max_length=1000)

    class Meta:
        unique_together = ('baserawactivity_ptr', 'jsonstr')
        verbose_name_plural = 'Questrade Raw Activities'

    def __str__(self):
        return self.jsonstr

    @classmethod
    def AllowDuplicate(cls, s):
        # Hack to support actual duplicate transactions (no disambiguation available)
        return s == '{"tradeDate": "2012-08-17T00:00:00.000000-04:00", "transactionDate": "2012-08-20T00:00:00.000000-04:00", "settlementDate": "2012-08-20T00:00:00.000000-04:00", "action": "Sell", "symbol": "", "symbolId": 0, "description": "CALL EWJ    01/19/13    10     ISHARES MSCI JAPAN INDEX FD    AS AGENTS, WE HAVE BOUGHT      OR SOLD FOR YOUR ACCOUNT   ", "currency": "USD", "quantity": -5, "price": 0.14, "grossAmount": null, "commission": -14.96, "netAmount": 55.04, "type": "Trades"}'

    @classmethod
    def Add(cls, json, account):
        """ Returns true if we added a new activity to the DB, false if it already existed. """
        s = simplejson.dumps(json)
        obj, created = QuestradeRawActivity.objects.get_or_create(jsonstr=s, account=account)
        if not created and cls.AllowDuplicate(s):
            s = s.replace('YOUR ACCOUNT   ', 'YOUR ACCOUNT X2')
            QuestradeRawActivity.objects.create(jsonstr=s, account=account)
            return True

        return created

    def GetCleanedJson(self):
        json = simplejson.loads(self.jsonstr)

        # Handle Options cleanup
        if json['description'].startswith('CALL ') or json['description'].startswith('PUT '):
            callput, symbol, expiry, strike = json['description'].split()[:4]
            expiry = datetime.datetime.strptime(expiry, '%m/%d/%y')
            security = Security.options.Create(callput, symbol, expiry, strike, json['currency'])
            json['symbol'] = security.symbol

            # Questrade options have price per share not per option.
            json['price'] *= security.price_multiplier

        # Hack to fix invalid Questrade data just for me
        if not json['symbol']:
            if 'ISHARES S&P/TSX 60 INDEX' in json['description']:          json['symbol'] = 'XIU.TO'
            elif 'VANGUARD GROWTH ETF' in json['description']:             json['symbol'] = 'VUG'
            elif 'SMALLCAP GROWTH ETF' in json['description']:             json['symbol'] = 'VBK'
            elif 'SMALL-CAP VALUE ETF' in json['description']:             json['symbol'] = 'VBR'
            elif 'ISHARES MSCI EAFE INDEX' in json['description']:         json['symbol'] = 'XIN.TO'
            elif 'AMERICAN CAPITAL AGENCY CORP' in json['description']:    json['symbol'] = 'AGNC'
            elif 'MSCI JAPAN INDEX FD' in json['description']:             json['symbol'] = 'EWJ'
            elif 'VANGUARD EMERGING' in json['description']:               json['symbol'] = 'VWO'
            elif 'VANGUARD MID-CAP GROWTH' in json['description']:         json['symbol'] = 'VOT'
            elif 'ISHARES DEX SHORT TERM BOND' in json['description']:     json['symbol'] = 'XBB.TO'
            elif 'ELECTRONIC ARTS INC' in json['description']:             json['symbol'] = 'EA'
            elif 'WESTJET AIRLINES' in json['description']:                json['symbol'] = 'WJA.TO'

        if json['symbol'] == 'TWMJF': json['symbol'] = 'WEED.TO'

        if json['action'] == 'FXT':
            if 'AS OF ' in json['description']:
                tradeDate = arrow.get(json['tradeDate'])

                asof = arrow.get(json['description'].split('AS OF ')[1].split(' ')[0], 'MM/DD/YY')
                # print("FXT Transaction at {} (asof date: {}). Timedelta is {}".format(tradeDate, asof, tradeDate-asof))
                if (tradeDate - asof).days > 365:
                    asof = asof.shift(years=+1)

                json['tradeDate'] = tradeDate.replace(
                    year=asof.year, month=asof.month, day=asof.day).isoformat()

        json['tradeDate'] = str(parser.parse(json['tradeDate']).date())
        json['type'] = QuestradeActivityType.objects.GetActivityType(json['type'], json['action'])
        json['qty'] = json['quantity']
        del json['quantity']

        if json['symbol']:
            try:
                json['security'] = Security.objects.get(symbol=json['symbol'])
            except Security.DoesNotExist:
                json['security'] = Security.objects.CreateStock(json['symbol'], json['currency'])
        else:
            json['security'] = None

        return json

    def CreateActivity(self):
        json = self.GetCleanedJson()

        create_args = {'account': self.account, 'raw': self}
        for item in ['description', 'tradeDate', 'type', 'security', 'commission']:
            create_args[item] = json[item]
        for item in ['price', 'netAmount', 'qty']:
            create_args[item] = Decimal(str(json[item]))

        create_args['cash_id'] = json['currency']

        Activity.objects.create(**create_args)


class QuestradeAccount(BaseAccount):
    curBalanceSynced = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    sodBalanceSynced = models.DecimalField(max_digits=19, decimal_places=4, default=0)

    def __str__(self):
        return "{} {} {}".format(self.client, self.id, self.type)

    def __repr__(self):
        return 'QuestradeAccount<{},{},{}>'.format(self.client, self.id, self.type)

    @property
    def cur_balance(self):
        return self.curBalanceSynced

    @property
    def yesterday_balance(self):
        return self.sodBalanceSynced

    def UpdateSyncedBalances(self, json):
        current = sum([
            Security.cash.get(symbol=entry['currency']).live_price * Decimal(str(entry['totalEquity']))
            for entry in json['perCurrencyBalances']
        ])
        sod = sum([
            Security.cash.get(symbol=entry['currency']).yesterday_price * Decimal(str(entry['totalEquity']))
            for entry in json['sodPerCurrencyBalances']
        ])
        self.curBalanceSynced = current
        self.sodBalanceSynced = sod
        self.save()


class QuestradeClient(BaseClient):
    username = models.CharField(max_length=32)
    refresh_token = models.CharField(max_length=100)
    access_token = models.CharField(max_length=100, null=True, blank=True)
    api_server = models.CharField(max_length=100, null=True, blank=True)
    token_expiry = models.DateTimeField(null=True, blank=True)
    authorization_lock = threading.Lock()

    def __repr__(self):
        return "QuestradeClient<{}>".format(self.display_name)

    @property
    def activitySyncDateRange(self):
        return 28

    @property
    def needs_refresh(self):
        """ Check if we should refresh this questrade token. At time of writing their API docs state the access token is good for 30 minutes."""
        if not self.token_expiry: return True
        if not self.access_token: return True
        # We need refresh if we are less than 10 minutes from expiry.
        return self.token_expiry < (timezone.now() - datetime.timedelta(seconds=600))

    def Authorize(self):
        assert self.refresh_token, "We don't have a refresh_token at all! How did that happen?"

        with self.authorization_lock:
            if self.needs_refresh:
                _URL_LOGIN = 'https://login.questrade.com/oauth2/token?grant_type=refresh_token&refresh_token='
                r = requests.get(_URL_LOGIN + self.refresh_token)
                r.raise_for_status()
                try:
                    json = r.json()
                    self.api_server = json['api_server'] + 'v1/'
                    self.refresh_token = json['refresh_token']
                    self.access_token = json['access_token']
                    self.token_expiry = timezone.now() + datetime.timedelta(seconds=json['expires_in'])
                    # Make sure to save out to DB
                    self.save()
                except simplejson.errors.JSONDecodeError:
                    print("Failed to get a valid Questrade access token for {}.".format(self))
                    raise ConnectionError()

        self.session = requests.Session()
        self.session.headers.update({'Authorization': 'Bearer' + ' ' + self.access_token})

    def CloseSession(self):
        self.session.close()

    def _GetRequest(self, url, params=None):
        if params is None:
            params = {}
        r = self.session.get(self.api_server + url, params=params)
        r.raise_for_status()
        return r.json()

    @api_response('accounts')
    def GetAccounts(self):
        return self._GetRequest('accounts')

    def SyncAccounts(self):
        for account_json in self.GetAccounts():
            QuestradeAccount.objects.get_or_create(
                type=account_json['type'], id=account_json['number'], client=self, defaults={'taxable' : False})
            
        AddManualRawActivity()

    def _CreateRawActivities(self, account, start, end):
        end = end.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            json = self._GetRequest('accounts/{}/activities'.format(account.id),
                                    {'startTime': start.isoformat(), 'endTime': end.isoformat()})
        except:
            return 0
        print("Get activities from source returned: " + simplejson.dumps(json))
        count = 0
        for activity_json in json['activities']:
            if QuestradeRawActivity.Add(activity_json, account):
                count += 1
        return count

    def SyncCurrentAccountBalances(self):
        for a in self.accounts.all():
            try:
                json = self._GetRequest('accounts/{}/balances'.format(a.id))
                a.UpdateSyncedBalances(json)
            except requests.exceptions.HTTPError as ex:
                print("Failed to connect to Questrade server: {}".format(ex))


tfsa_activity_data = [
    ('6/3/2009', 'Deposit', '', 'CAD', '', '', '1000', ''),
    ('6/8/2009', 'Deposit', '', 'CAD', '', '', '4000', ''),

    ('6/15/2009', 'Buy', 'GE', 'USD', '13.73', '150', '-2064.45', ''),
    ('6/15/2009', 'Buy', 'IGR', 'USD', '5.25', '200', '-1054.95', ''),
    ('6/15/2009', 'Buy', 'VUG', 'USD', '44.58', '30', '-1342.35', ''),
    ('6/15/2009', 'FX', '', 'CAD', '', '', '-4969.50', 'AUTO CONV @ 1.1138 %US PREM'),
    ('6/15/2009', 'FX', '', 'USD', '', '', '4461.75', 'AUTO CONV @ 1.1138 %US PREM'),

    ('6/15/2009', 'Sell', 'GE    090718C00014000', 'USD', '54', '-1', '43.05', ''),
    ('6/15/2009', 'FX', '', 'CAD', '', '', '47.97', 'AUTO CONV @ 1.1142 %US PREM'),
    ('6/15/2009', 'FX', '', 'USD', '', '', '-43.05', 'AUTO CONV @ 1.1142 %US PREM'),

    ('6/30/2009', 'Dividend', 'IGR', 'USD', '', '', '7.65', ''),
    ('6/30/2009', 'Dividend', 'VUG', 'USD', '', '', '3.70', ''),
    ('6/30/2009', 'FX', '', 'CAD', '', '', '13.09', 'AUTO CONV @ 1.15350 %US PREM'),
    ('6/30/2009', 'FX', '', 'USD', '', '', '-11.35', 'AUTO CONV @ 1.15350 %US PREM'),

    ('7/7/2009', 'Buy', 'EA    090721C00021000', 'USD', '70', '1', '-80.95', ''),
    ('7/7/2009', 'FX', '', 'CAD', '', '', '-94.33', 'AUTO CONV @ 1.1653 %US PREM'),
    ('7/7/2009', 'FX', '', 'USD', '', '', '80.95', 'AUTO CONV @ 1.1653 %US PREM'),

    ('7/17/2009', 'Expiry', 'GE    090718C00014000', 'USD', '', '1', '', ''),
    ('7/17/2009', 'Expiry', 'EA    090721C00021000', 'USD', '', '-1', '', ''),

    ('7/27/2009', 'Dividend', 'GE', 'USD', '', '', '12.75', ''),
    ('7/27/2009', 'FX', '', 'CAD', '', '', '13.69', 'AUTO CONV @ 1.074 %US PREM'),
    ('7/27/2009', 'FX', '', 'USD', '', '', '-12.75', 'AUTO CONV @ 1.074 %US PREM'),

    ('7/31/2009', 'Dividend', 'IGR', 'USD', '', '', '7.65', ''),
    ('7/31/2009', 'FX', '', 'CAD', '', '', '8.2', 'AUTO CONV @ 1.07250 %US PREM'),
    ('7/31/2009', 'FX', '', 'USD', '', '', '-7.65', 'AUTO CONV @ 1.07250 %US PREM'),

    ('8/10/2009', 'Sell', 'GE', 'USD', '14', '-50', '695.02', ''),
    ('8/10/2009', 'Sell', 'IGR', 'USD', '6.08', '-200', '1211.01', ''),
    ('8/10/2009', 'Buy', 'IGR', 'USD', '6.07', '100', '-611.95', ''),
    ('8/10/2009', 'FX', '', 'CAD', '', '', '1378.72', 'AUTO CONV @ 1.0654 %US PREM'),
    ('8/10/2009', 'FX', '', 'USD', '', '', '-1294.08', 'AUTO CONV @ 1.0654 %US PREM'),
    ('8/10/2009', 'Buy', 'WJA.TO', 'CAD', '10.69', '100', '-1073.95', ''),

    ('8/21/2009', 'Fee', '', 'CAD', '', '', '-0.53', ''),
    ('8/25/2009', 'Buy', 'HXU.TO', 'CAD', '15.36', '20', '-312.22', ''),

    ('8/31/2009', 'Dividend', 'IGR', 'USD', '', '100', '3.82', ''),
    ('8/31/2009', 'FX', '', 'CAD', '', '', '4.15', 'AUTO CONV @ 1.08750 %US PREM'),
    ('8/31/2009', 'FX', '', 'USD', '', '', '-3.82', 'AUTO CONV @ 1.08750 %US PREM'),

    ('9/10/2009', 'Sell', 'HXU.TO', 'CAD', '16.12', '-20', '317.38', ''),
    ('9/18/2009', 'Fee', '', 'CAD', '', '', '-2.63', ''),

    ('9/21/2009', 'Sell', 'GE', 'USD', '16.722', '-100', '1667.25', ''),
    ('9/21/2009', 'Buy', 'VBK', 'USD', '57.75', '34', '-1968.45', ''),
    ('9/21/2009', 'FX', '', 'CAD', '', '', '-322.57', 'AUTO CONV @ 1.071 %US PREM'),
    ('9/21/2009', 'FX', '', 'USD', '', '', '301.20', 'AUTO CONV @ 1.071 %US PREM'),

    ('9/30/2009', 'Dividend', 'IGR', 'USD', '', '100', '3.82', ''),
    ('9/30/2009', 'Dividend', 'VUG', 'USD', '', '30', '3.62', ''),
    ('9/30/2009', 'FX', '', 'CAD', '', '', '7.91', 'AUTO CONV @ 1.0625 %US PREM'),
    ('9/30/2009', 'FX', '', 'USD', '', '', '-7.44', 'AUTO CONV @ 1.0625 %US PREM'),

    ('10/14/2009', 'Fee', '', 'CAD', '', '', '-1.58', ''),

    ('10/30/2009', 'Dividend', 'IGR', 'USD', '', '100', '3.82', ''),
    ('10/30/2009', 'FX', '', 'CAD', '', '', '4.09', 'AUTO CONV @ 1.07100 %US PREM'),
    ('10/30/2009', 'FX', '', 'USD', '', '', '-3.82', 'AUTO CONV @ 1.07100 %US PREM'),

    ('11/30/2009', 'Dividend', 'IGR', 'USD', '', '100', '3.82', ''),
    ('11/30/2009', 'FX', '', 'CAD', '', '', '4.01', 'AUTO CONV @ 1.04850 %US PREM'),
    ('11/30/2009', 'FX', '', 'USD', '', '', '-3.82', 'AUTO CONV @ 1.04850 %US PREM'),

    ('12/7/2009', 'Buy', 'ECA.TO', 'CAD', '56.13', '33', '-1857.36', ''),
    ('12/7/2009', 'Sell', 'ECA.TO', 'CAD', '56.24', '-33', '1850.85', ''),

    ('12/7/2009', 'Sell', 'IGR', 'USD', '6.14', '-100', '609.05', ''),
    ('12/7/2009', 'Buy', 'MCD', 'USD', '62.91', '28', '-1766.43', ''),
    ('12/7/2009', 'FX', '', 'CAD', '', '', '-1222.68', 'AUTO CONV @ 1.0564 %US PREM'),
    ('12/7/2009', 'FX', '', 'USD', '', '', '1157.38', 'AUTO CONV @ 1.0564 %US PREM'),

    ('12/7/2009', 'Sell', 'WJA.TO', 'CAD', '12', '-100', '1195.05', ''),

    ('12/11/2009', 'Sell', 'MCD', 'USD', '60.62', '-1', '55.67', ''),
    ('12/11/2009', 'FX', '', 'CAD', '', '', '58.9', 'AUTO CONV @ 1.058 %US PREM'),
    ('12/11/2009', 'FX', '', 'USD', '', '', '-55.67', 'AUTO CONV @ 1.058 %US PREM'),

    ('12/29/2009', 'Dividend', 'VUG', 'USD', '', '30', '4.56', ''),
    ('12/29/2009', 'FX', '', 'CAD', '', '', '4.72', 'AUTO CONV @ 1.03600 %US PREM'),
    ('12/29/2009', 'FX', '', 'USD', '', '', '-4.56', 'AUTO CONV @ 1.03600 %US PREM'),

    ('12/31/2009', 'Dividend', 'VBK', 'USD', '', '34', '6.61', ''),
    ('12/31/2009', 'FX', '', 'CAD', '', '', '6.87', 'AUTO CONV @ 1.03900 %US PREM'),
    ('12/31/2009', 'FX', '', 'USD', '', '', '-6.61', 'AUTO CONV @ 1.03900 %US PREM'),
    ('1/5/2010', 'Deposit', '', 'CAD', '', '', '5000', ''),

    ('1/11/2010', 'Buy', 'VUG', 'USD', '54.08', '88', '-4763.99', ''),
    ('1/11/2010', 'FX', '', 'CAD', '', '', '-4941.21', 'AUTO CONV @ 1.0372 %US PREM'),
    ('1/11/2010', 'FX', '', 'USD', '', '', '4763.99', 'AUTO CONV @ 1.0372 %US PREM'),

    ('1/29/2010', 'Buy', 'ATVI', 'USD', '10.08', '175', '-1768.95', ''),
    ('1/29/2010', 'Sell', 'MCD', 'USD', '63.39', '-27', '1706.55', ''),
    ('1/29/2010', 'FX', '', 'CAD', '', '', '-66.63', 'AUTO CONV @ 1.0677 %US PREM'),
    ('1/29/2010', 'FX', '', 'USD', '', '', '62.4', 'AUTO CONV @ 1.0677 %US PREM'),

    ('3/31/2010', 'Dividend', 'VUG', 'USD', '', '118', '14.55', ''),
    ('3/31/2010', 'FX', '', 'CAD', '', '', '14.67', 'AUTO CONV @ 1.00850 %US PREM'),
    ('3/31/2010', 'FX', '', 'USD', '', '', '-14.55', 'AUTO CONV @ 1.00850 %US PREM'),

    ('4/5/2010', 'Dividend', 'ATVI', 'USD', '', '175', '22.31', ''),
    ('4/5/2010', 'FX', '', 'CAD', '', '', '22.27', 'AUTO CONV @ 0.99800 %US PREM'),
    ('4/5/2010', 'FX', '', 'USD', '', '', '-22.31', 'AUTO CONV @ 0.99800 %US PREM'),

    ('6/30/2010', 'Dividend', 'VUG', 'USD', '', '118', '14.94', ''),
    ('9/30/2010', 'Dividend', 'VUG', 'USD', '', '118', '20.36', ''),
    ('11/12/2010', 'Sell', 'ATVI', 'USD', '11.83', '-175', '2065.3', ''),
    ('11/15/2010', 'Buy', 'AGNC', 'USD', '29.23', '70', '-2051.05', ''),
    ('12/15/2010', 'Fee', '', 'CAD', '', '', '4.95', ''),
    ('12/31/2010', 'Dividend', 'VBK', 'USD', '', '', '10.41', ''),
    ('12/31/2010', 'Dividend', 'VUG', 'USD', '', '', '20.36', ''),
]

rrsp_activity_data = [
    ('11/2/2009', 'Transfer', '', 'CAD', '', '', '6951.09', 'RE: SEC.146(16) ITA'),
    ('11/12/2009', 'Buy', 'XIU.TO', 'CAD', '16.77', '200', '-3359.69', ''),

    ('11/12/2009', 'Buy', 'VWO', 'USD', '39.66', '80', '-3177.75', ''),
    ('11/12/2009', 'FX', '', 'CAD', '', '', '-3430.38', 'AUTO CONV @ 1.0795 %US PREM'),
    ('11/12/2009', 'FX', '', 'USD', '', '', '3177.75', 'AUTO CONV @ 1.0795 %US PREM'),

    ('12/31/2009', 'Dividend', 'XIU.TO', 'CAD', '', '200', '21.17', ''),

    ('12/31/2009', 'Dividend', 'VWO', 'USD', '', '80', '43.6', ''),
    ('12/31/2009', 'FX', '', 'CAD', '', '', '45.3', 'AUTO CONV @ 1.03900 %US PREM'),
    ('12/31/2009', 'FX', '', 'USD', '', '', '-43.6', 'AUTO CONV @ 1.03900 %US PREM'),

    ('2/24/2010', 'Deposit', '', 'CAD', '', '', '6000', ''),
    ('3/2/2010', 'Buy', 'VOT', 'USD', '47.83', '120', '-5744.55', ''),
    ('3/2/2010', 'FX', '', 'CAD', '', '', '-6121.97', 'AUTO CONV @ 1.0657 %US PREM'),
    ('3/2/2010', 'FX', '', 'USD', '', '', '5744.55', 'AUTO CONV @ 1.0657 %US PREM'),

    ('3/24/2010', 'Fee', '', 'CAD', '', '', '-0.53', ''),
    ('3/31/2010', 'Dividend', 'XIU.TO', 'CAD', '', '200', '24.34', ''),
    ('4/1/2010', 'Deposit', '', 'CAD', '', '', '6000', ''),

    ('4/13/2010', 'Buy', 'VWO', 'USD', '43.33', '140', '-6071.15', ''),
    ('4/13/2010', 'FX', '', 'CAD', '', '', '-6119.72', 'AUTO CONV @ 1.008 %US PREM'),
    ('4/13/2010', 'FX', '', 'USD', '', '', '6071.15', 'AUTO CONV @ 1.008 %US PREM'),

    ('5/13/2010', 'Fee', '', 'CAD', '', '', '-0.53', ''),
    ('6/17/2010', 'Deposit', '', 'CAD', '', '', '5000', ''),
    ('6/24/2010', 'FX', '', 'CAD', '', '', '-4764.75', ''),
    ('6/24/2010', 'FX', '', 'USD', '', '', '4543.92', ''),
    ('6/29/2010', 'Buy', 'EA', 'USD', '15.129', '300', '-4543.92', ''),
    ('6/30/2010', 'Dividend', 'XIU.TO', 'CAD', '', '200', '21.81', ''),
    ('9/30/2010', 'Dividend', 'XIU.TO', 'CAD', '', '200', '22.21', ''),
    ('10/4/2010', 'Sell', 'EA    101120C00018000', 'USD', '44', '-3', '119.04', ''),
    ('11/19/2010', 'Expiry', 'EA    101120C00018000', 'USD', '', '3', '', ''),
    ('12/31/2010', 'Dividend', 'XIU.TO', 'CAD', '', '200', '20.76', ''),
    ('12/29/2010', 'Dividend', 'VWO', 'USD', '', '220', '179.3', ''),
    ('12/31/2010', 'Dividend', 'VOT', 'USD', '', '120', '38.64', ''),
    ('1/12/2011', 'Sell', 'EA    110219C00017000', 'USD', '40', '-3', '107.04', ''),
    ('1/25/2011', 'Deposit', '', 'CAD', '', '', '7000', ''),
    ('1/26/2011', 'FX', '', 'CAD', '', '', '187.4', ''),
    ('1/26/2011', 'FX', '', 'USD', '', '', '-189.37', ''),
    ('1/31/2011', 'Buy', 'XSB.TO', 'CAD', '28.81', '260', '-7496.51', ''),
    ('2/3/2011', 'Buy', 'EA    110219C00017000', 'USD', '120', '3', '-372.95', ''),
    ('2/7/2011', 'Sell', 'EA', 'USD', '18.063', '-300', '5413.94', '')
]

sarah_tfsa_data = [
    ('1/1/2011', 'Deposit', 'VBR', 'USD', '0', '90', '', 'Faked past history - fix this with real data'),
    ('1/1/2011', 'Deposit', 'XSB.TO', 'CAD', '0', '85', '', 'Faked past history - fix this with real data'),
    ('1/1/2011', 'Deposit', 'XIN.TO', 'CAD', '0', '140', '', 'Faked past history - fix this with real data'),
    ('1/1/2011', 'Deposit', '', 'CAD', '', '', '147.25', 'Faked past history - fix this with real data'),
    ('1/1/2011', 'Deposit', '', 'USD', '', '', '97.15', 'Faked past history - fix this with real data'),
    ]


def AddManualRawActivity():
    ManualRawActivity.objects.all().delete()
    for account_id, data in [(51407958, tfsa_activity_data),
                             (51419220, sarah_tfsa_data),
                             (51424829, rrsp_activity_data)
                             ]:
        for date, type, symbol, currency, price, qty, netAmount, description in data:
            act = ManualRawActivity.objects.create(day=parser.parse(date),
                                    symbol=symbol,
                                    type=type,
                                    currency=currency,
                                    qty=qty if qty else '0',
                                    price=price if price else '0',
                                    netAmount=netAmount if netAmount else '0',
                                    description=description,
                                    account_id=account_id)
