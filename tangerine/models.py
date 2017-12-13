from django.db import models

import requests
import tangerine.tangerinelib
from dateutil import parser

from finance.models import Activity, BaseAccount, BaseClient, BaseRawActivity, MutualFund


class TangerineRawActivity(BaseRawActivity):
    day = models.DateField()
    description = models.CharField(max_length=1000)
    activity_id = models.CharField(max_length=32, unique=True)
    type = models.CharField(max_length=32)
    symbol = models.CharField(max_length=100)
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)

    def __str__(self):
        return '{}: Bought {} {} at {}'.format(self.day, self.qty, self.symbol, self.price)

    def __repr__(self):
        return 'TangerineRawActivity<{},{},{},{},{}>'.format(self.account, self.day, self.symbol, self.qty, self.price)

    def CreateActivity(self):
        if self.symbol == 'Tangerine Equity Growth Portfolio':
            symbol = 'F00000NNHK'
            currency = 'CAD'
        else: assert False, 'Need a real lookup system here'

        try:
            security = MutualFund.objects.get(symbol=symbol)
        except:
            security = MutualFund.Create(symbol, currency)

        if self.type == 'Purchase':
            activity_type = Activity.Type.Buy
        else:
            activity_type = Activity.Type.Dividend

            
        total_cost = self.qty*self.price

        Activity.objects.create(account=self.account, tradeDate=self.day, security=None, cash_id=security.currency.code + ' Cash',
                                description='Generated Deposit', qty=0,
                        price=0, netAmount=total_cost, type=Activity.Type.Deposit, raw=self)
            
        Activity.objects.create(account=self.account, tradeDate=self.day, security=security, cash_id=security.currency.code + ' Cash',
                                description=self.description, qty=self.qty,
                        price=self.price, netAmount=-total_cost, type=activity_type, raw=self)


class TangerineAccount(BaseAccount):
    internal_display_name = models.CharField(max_length=100)
    account_balance = models.DecimalField(max_digits=16, decimal_places=6)

    def __str__(self):
        return self.internal_display_name

    def __repr__(self):
        return "TangerineAccount<{}>".format(self.id)

    @property
    def cur_balance(self):
        return self.account_balance


class TangerineClient(BaseClient):
    username = models.CharField(max_length=32)
    password = models.CharField(max_length=100)
    securityq1 = models.CharField(max_length=1000)
    securitya1 = models.CharField(max_length=100)
    securityq2 = models.CharField(max_length=1000)
    securitya2 = models.CharField(max_length=100)
    securityq3 = models.CharField(max_length=1000)
    securitya3 = models.CharField(max_length=100)

    def __repr__(self):
        return 'TangerineClient<{}>'.format(self.display_name)

    @property
    def activitySyncDateRange(self):
        return 2000

    def _GetRequest(self, url, params={}):
        r = requests.get(url, params=params)
        r.raise_for_status()
        return r.json()

    def Authorize(self):
        secrets_dict = {'username': self.username, 'password': self.password,
                        'security_questions': {
                            self.securityq1: self.securitya1,
                            self.securityq2: self.securitya2,
                            self.securityq3: self.securitya3}}

        secrets = tangerine.tangerinelib.DictionaryBasedSecretProvider(secrets_dict)
        self.client = tangerine.tangerinelib.TangerineClient(secrets)

    def SyncAccounts(self):
        with self.client.login():
            accounts = self.client.list_accounts()
            for a in accounts:
                TangerineAccount.objects.get_or_create(client=self, id=a['number'], defaults={
                                                       'type': a['description'], 'internal_display_name': a['display_name'], 'account_balance': a['account_balance']})

    def _CreateRawActivities(self, account, start, end):
        with self.client.login():
            transactions = self.client.list_transactions([account.id], start.date(), end.date())
            count = 0
            for trans in transactions:
                obj, created = TangerineRawActivity.objects.get_or_create(activity_id=trans['id'], account=account, defaults={
                    'day': parser.parse(trans['transaction_date']).date(),
                    'description': trans['description'],
                    'type': trans['mutual_fund']['transaction_type'],
                    'symbol': trans['mutual_fund']['portfolio_name'],
                    'qty': trans['mutual_fund']['units'],
                    'price': trans['mutual_fund']['unit_price']
                    })
                if created: count += 1
            return count
