import datetime
import threading
from decimal import Decimal
from json import dumps, loads, JSONDecodeError

import pendulum
import requests
from dateutil import parser
from django.db import models, transaction
from django.utils import timezone

from datasource.models import DataSourceMixin
from finance.models import Activity
from finance.models import BaseRawActivity, BaseAccount, ManualRawActivity
from finance.models import BaseRawActivityQuerySet
from securities.models import Security, Option
from utils.api import api_response


class QuestradeActivityTypeManager(models.Manager):
    def GetActivityType(self, type, action):
        try:
            return self.get(q_type=type, q_action=action).activity_type
        except QuestradeActivityType.DoesNotExist:
            print('No action type mapping for "{}" "{}"'.format(type, action))
            return Activity.Type.NotImplemented


class QuestradeActivityType(models.Model):
    q_type = models.CharField(max_length=32)
    q_action = models.CharField(max_length=32)
    activity_type = models.CharField(max_length=32)
    objects = QuestradeActivityTypeManager()


class QuestradeRawActivityQuerySet(BaseRawActivityQuerySet):
    def get_or_create(self, defaults=None, **kwargs):
        obj, created = super().get_or_create(defaults, **kwargs)
        if not created and self.model.AllowDuplicate(kwargs['jsonstr']):
            kwargs['jsonstr'] = kwargs['jsonstr'].replace('YOUR ACCOUNT   ', 'YOUR ACCOUNT X2')
            obj = super().create(**kwargs)
            return obj, True
        return obj, created


class QuestradeRawActivity(BaseRawActivity):
    jsonstr = models.CharField(max_length=1000)

    objects = QuestradeRawActivityQuerySet.as_manager()

    class Meta:
        unique_together = ('baserawactivity_ptr', 'jsonstr')
        verbose_name_plural = 'Questrade Raw Activities'

    def __str__(self):
        return self.jsonstr

    @classmethod
    def AllowDuplicate(cls, s):
        # Hack to support actual duplicate transactions (no disambiguation available)
        # TODO: This should go in the database... somehow...
        return s == '{"trade_date": "2012-08-17T00:00:00.000000-04:00", "transactionDate": "2012-08-20T00:00:00.000000-04:00", "settlementDate": "2012-08-20T00:00:00.000000-04:00", "action": "Sell", "symbol": "", "symbolId": 0, "description": "CALL EWJ    01/19/13    10     ISHARES MSCI JAPAN INDEX FD    AS AGENTS, WE HAVE BOUGHT      OR SOLD FOR YOUR ACCOUNT   ", "currency": "USD", "quantity": -5, "price": 0.14, "grossAmount": null, "commission": -14.96, "net_amount": 55.04, "type": "Trades"}'

    def GetCleanedJson(self):
        json = loads(self.jsonstr)

        # Handle Options cleanup
        if json['description'].startswith('CALL ') or json['description'].startswith('PUT '):
            callput, symbol, expiry, strike = json['description'].split()[:4]
            symbol = symbol.strip('.')
            expiry = datetime.datetime.strptime(expiry, '%m/%d/%y')
            security = Option.objects.CreateFromDetails(callput, symbol, expiry, strike, json['currency'])
            json['symbol'] = security.symbol
            security.add_datasource(QuestradeOptionDataSource.create_from_option(
                security, self.account.client))

            # Questrade options have price per share not per option.
            json['price'] *= security.price_multiplier

        # TODO: This should be in a database table for sure.
        if not json['symbol']:
            if 'ISHARES S&P/TSX 60 INDEX' in json['description']:          json['symbol'] = 'XIU'
            elif 'VANGUARD GROWTH ETF' in json['description']:             json['symbol'] = 'VUG'
            elif 'SMALLCAP GROWTH ETF' in json['description']:             json['symbol'] = 'VBK'
            elif 'SMALL-CAP VALUE ETF' in json['description']:             json['symbol'] = 'VBR'
            elif 'ISHARES MSCI EAFE INDEX' in json['description']:         json['symbol'] = 'XIN'
            elif 'AMERICAN CAPITAL AGENCY CORP' in json['description']:    json['symbol'] = 'AGNC'
            elif 'MSCI JAPAN INDEX FD' in json['description']:             json['symbol'] = 'EWJ'
            elif 'VANGUARD EMERGING' in json['description']:               json['symbol'] = 'VWO'
            elif 'EMERGING MKTS' in json['description']:                   json['symbol'] = 'VWO'
            elif 'VANGUARD MID-CAP GROWTH' in json['description']:         json['symbol'] = 'VOT'
            elif 'ISHARES DEX SHORT TERM BOND' in json['description']:     json['symbol'] = 'XBB'
            elif 'ELECTRONIC ARTS INC' in json['description']:             json['symbol'] = 'EA'
            elif 'WESTJET AIRLINES' in json['description']:                json['symbol'] = 'WJA'

        if json['symbol'] == 'TWMJF': json['symbol'] = 'WEED'
        if json['symbol'].endswith('.TO'):
            json['symbol'] = json['symbol'][:-3]

        if json['action'] == 'FXT':
            if 'AS OF ' in json['description']:
                trade_date = pendulum.parse(json['trade_date'])
                asof = pendulum.from_format(json['description'].split('AS OF ')[1].split(' ')[0], '%m/%d/%y')
                if (trade_date - asof).days > 365:
                    asof = asof.add(years=1)
                json['trade_date'] = asof.isoformat()

        json['trade_date'] = str(parser.parse(json['trade_date']).date())
        json['type'] = QuestradeActivityType.objects.GetActivityType(json['type'], json['action'])
        json['qty'] = json['quantity']
        del json['quantity']

        json['cash_id'] = json['currency']

        if json['symbol']:
            json['security'], _ = Security.objects.get_or_create(symbol=json['symbol'],
                                                                 defaults={'currency': json['currency']})
        else:
            json['security'] = None

        return json

    def CreateActivity(self):
        json = self.GetCleanedJson()

        create_args = {'account': self.account, 'raw': self}
        for item in ['description', 'trade_date', 'type', 'security', 'commission', 'cash_id']:
            create_args[item] = json[item]
        for item in ['price', 'net_amount', 'qty']:
            create_args[item] = Decimal(str(json[item]))

        Activity.objects.create(**create_args)


class QuestradeClient(models.Model):
    username = models.CharField(max_length=32)
    refresh_token = models.CharField(max_length=100)
    access_token = models.CharField(max_length=100, null=True, blank=True)
    api_server = models.CharField(max_length=100, null=True, blank=True)
    token_expiry = models.DateTimeField(null=True, blank=True)
    authorization_lock = threading.Lock()

    def __str__(self):
        return self.username

    def __repr__(self):
        return "QuestradeClient<{}>".format(self.username)

    def __enter__(self):
        self.Authorize()
        return self

    def __exit__(self, type, value, traceback):
        self.session.close()

    @property
    def needs_refresh(self):
        """ Check if we should refresh this questrade token. At time of writing their API docs state the access token is good for 30 minutes."""
        if not self.token_expiry: return True
        if not self.access_token: return True
        # We need refresh if we are less than 10 minutes from expiry.
        return self.token_expiry < (timezone.now() - datetime.timedelta(seconds=600))

    @classmethod
    def UpdateAccessToken(cls, pk):
        with transaction.atomic():
            client = cls.objects.select_for_update().get(pk=pk)
            _URL_LOGIN = 'https://login.questrade.com/oauth2/token?grant_type=refresh_token&refresh_token='
            r = requests.get(_URL_LOGIN + client.refresh_token)
            r.raise_for_status()
            try:
                json = r.json()
                client.api_server = json['api_server'] + 'v1/'
                client.refresh_token = json['refresh_token']
                client.access_token = json['access_token']
                client.token_expiry = timezone.now() + datetime.timedelta(seconds=json['expires_in'])
                client.save()
            except JSONDecodeError:
                print("Failed to get a valid Questrade access token for {}.".format(client))
                print("The request result was {}".format(r.content))
                raise ConnectionError()

    def Authorize(self, force=False):
        assert self.refresh_token, "We don't have a refresh_token at all! How did that happen?"
        if self.needs_refresh or force:
            self.UpdateAccessToken(self.pk)
            self.refresh_from_db()

        self.session = requests.Session()
        self.session.headers.update({'Authorization': 'Bearer' + ' ' + self.access_token})

    def _GetRequest(self, url, params=None):
        if params is None:
            params = {}
        r = self.session.get(self.api_server + url, params=params)
        r.raise_for_status()
        return r.json()

    @api_response('accounts')
    def GetAccounts(self):
        return self._GetRequest('accounts')

    def GetSymbolIds(self, symbols):
        symbols += [s+'.TO' for s in symbols]
        json = self._GetRequest('symbols', params={'names' : ','.join(symbols)})
        for entry in json['symbols']:
            yield entry['symbolId']

    def GetSymbolId(self, symbol):
        return next(self.GetSymbolIds([symbol]))

    def GetOptionId(self, underlying_id, expiry, type, strike):
        """
        :param underlying_id: the Questrade ID of the underlying
        :param expiry: datetime, expiry date
        :param type: 'call' or 'put'
        :param strike: strike price
        :return:
        """
        chain_json = self._GetRequest('symbols/{}/options'.format(underlying_id))
        for chain in chain_json['optionChain']:
            if parser.parse(chain['expiryDate']).date() == expiry.date():
                for root in chain['chainPerRoot']:
                    for option in chain['chainPerRoot'][0]['chainPerStrikePrice']:
                        if abs(option['strikePrice'] - strike) < 0.01:
                            return option['callSymbolId'] if type.lower() == 'call' else option['putSymbolId']
        return 0

    def GetOptionPrice(self, option_id):
        response = self.session.post(self.api_server + 'markets/quotes/options', json={'optionIds':[option_id]})
        response.raise_for_status()
        json = response.json()
        data = json['optionQuotes'][0]
        if data['lastTradePriceTrHrs']:
            return data['lastTradePriceTrHrs']
        if data['lastTradePrice']:
            return data['lastTradePrice']
        return None

    @api_response()
    def GetAccountBalances(self, id):
        return self._GetRequest('accounts/{}/balances'.format(id))

    @api_response('activities')
    def GetActivities(self, account_id, start, end):
        start = pendulum.create(start.year, start.month, start.day)
        end = pendulum.create(end.year, end.month, end.day)
        json = self._GetRequest('accounts/{}/activities'.format(account_id),
                                {'startTime': start.isoformat(), 'endTime': end.isoformat()})
        print("Get activities from source returned: " + dumps(json))
        return json

    def SyncAccounts(self):
        for account_json in self.GetAccounts():
            QuestradeAccount.objects.get_or_create(
                type=account_json['type'], id=account_json['number'], client=self)


class QuestradeOptionDataSource(DataSourceMixin):
    symbol = models.CharField(max_length=32)
    optionid = models.IntegerField()
    client = models.ForeignKey(QuestradeClient, on_delete=models.CASCADE)

    def __str__(self):
        return "Questrade Client {} for option {}".format(self.client, self.symbol)

    def __repr__(self):
        return "QuestradeOptionDataSource<{},{}>".format(self.symbol, self.client)

    @classmethod
    def create_from_option(cls, option, client):
        with client as c:
            underlying_id = c.GetSymbolId(option.underlying)
            optionid = c.GetOptionId(underlying_id, option.expiry, 'call' if option.is_call else 'put', option.strike)

        return cls(symbol=option.symbol, optionid=optionid, client=client)

    def _Retrieve(self, start, end):
        with self.client as client:
            multiplier = Security.options.get(symbol=self.symbol).price_multiplier
            return [(datetime.date.today(), multiplier * client.GetOptionPrice(self.optionid))]


class QuestradeAccount(BaseAccount):
    client = models.ForeignKey(QuestradeClient, on_delete=models.DO_NOTHING, null=True, blank=True)
    curBalanceSynced = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    sodBalanceSynced = models.DecimalField(max_digits=19, decimal_places=4, default=0)

    activitySyncDateRange = 28

    def __str__(self):
        return "{} {} {}".format(self.client, self.account_id, self.type)

    def __repr__(self):
        return 'QuestradeAccount<{},{},{}>'.format(self.client, self.account_id, self.type)

    @property
    def cur_balance(self):
        return self.curBalanceSynced

    @property
    def yesterday_balance(self):
        return self.sodBalanceSynced

    def CreateActivities(self, start, end):
        with self.client as client:
            for json in client.GetActivities(self.account_id, start, end):
                QuestradeRawActivity.objects.get_or_create(account=self, jsonstr=dumps(json))

    def SyncBalances(self):
        with self.client as client:
            try:
                json = client.GetAccountBalances(self.account_id)
                self.curBalanceSynced = sum([
                    Security.cash.get(symbol=entry['currency']).live_price * Decimal(str(entry['totalEquity']))
                    for entry in json['perCurrencyBalances']
                ])
                self.sodBalanceSynced = sum([
                    Security.cash.get(symbol=entry['currency']).yesterday_price * Decimal(str(entry['totalEquity']))
                    for entry in json['sodPerCurrencyBalances']
                ])
                self.save()
            except requests.exceptions.HTTPError:
                pass

