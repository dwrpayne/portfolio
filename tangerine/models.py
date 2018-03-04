from decimal import Decimal

import requests
from dateutil import parser
from django.db import models
from fernet_fields import EncryptedTextField

import tangerine.tangerinelib
from finance.models import Activity, BaseAccount, BaseRawActivity
from securities.models import Security


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
        else:
            assert False, 'Need a real lookup system here'

        try:
            security = Security.mutualfunds.get(symbol=symbol)
        except Security.DoesNotExist:
            security = Security.mutualfunds.Create(symbol, currency)

        creation_fn = Activity.objects.create

        net_amount = 0
        if self.type in ['Purchase', 'Transfer In']:
            activity_type = Activity.Type.Buy
            creation_fn = Activity.objects.create_with_deposit
            net_amount = -(Decimal(self.qty) * Decimal(self.price))
        elif self.type == 'Distribution':
            # Tangerine uses this to indicate a DRIP - aka deposit of shares
            # We'll consider it a Buy, with no cash effect and no associated deposit
            activity_type = Activity.Type.Buy
        elif self.type == 'Redemption':
            activity_type = Activity.Type.Sell
            creation_fn = Activity.objects.create_with_withdrawal
            net_amount = -(Decimal(self.qty) * Decimal(self.price))
        else:
            activity_type = Activity.Type.NotImplemented

        creation_fn(account=self.account, trade_date=self.day, security=security,
                    cash_id=security.currency,
                    description=self.description, qty=self.qty,
                    price=self.price, net_amount=net_amount, type=activity_type, raw=self)


class TangerineClient(models.Model):
    username = models.CharField(max_length=32)
    password = EncryptedTextField()
    securityq1 = models.CharField(max_length=1000)
    securitya1 = EncryptedTextField()
    securityq2 = models.CharField(max_length=1000)
    securitya2 = EncryptedTextField()
    securityq3 = models.CharField(max_length=1000)
    securitya3 = EncryptedTextField()

    def __str__(self):
        return self.username

    def __repr__(self):
        return 'TangerineClient<{}>'.format(self.username)

    def __enter__(self):
        secrets_dict = {'username': self.username, 'password': self.password,
                        'security_questions': {
                            self.securityq1: self.securitya1,
                            self.securityq2: self.securitya2,
                            self.securityq3: self.securitya3}}

        secrets = tangerine.tangerinelib.DictionaryBasedSecretProvider(secrets_dict)
        self.client = tangerine.tangerinelib.TangerineClient(secrets)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def SyncAccounts(self):
        try:
            with self.client.login():
                accounts = self.client.list_accounts()
                for a in accounts:
                    TangerineAccount.objects.get_or_create(client=self, id=a['number'], defaults={
                        'type': a['description'], 'internal_display_name': a['display_name'],
                        'account_balance': a['account_balance']})
        except requests.exceptions.HTTPError:
            print("Couldn't sync accounts - possible server failure?")

    def GetActivities(self, account_id, start, end):
        with self.client.login():
            return self.client.list_transactions([account_id], start, end)


class TangerineAccount(BaseAccount):
    client = models.ForeignKey(TangerineClient, on_delete=models.DO_NOTHING, null=True, blank=True)
    internal_display_name = models.CharField(max_length=100)
    account_balance = models.DecimalField(max_digits=16, decimal_places=6)

    activitySyncDateRange = 2000

    def __str__(self):
        return self.internal_display_name

    def __repr__(self):
        return "TangerineAccount<{}>".format(self.account_id)

    @property
    def cur_balance(self):
        return self.account_balance

    def CreateActivities(self, start, end):
        with self.client as client:
            for trans in client.GetActivities(self.account_id, start, end):
                TangerineRawActivity.objects.get_or_create(account=self, activity_id=trans['id'],
                                       defaults={
                                           'day': parser.parse(trans['transaction_date']).date(),
                                           'description': trans['description'],
                                           'type': trans['mutual_fund']['transaction_type'],
                                           'symbol': trans['mutual_fund']['portfolio_name'],
                                           'qty': trans['mutual_fund']['units'],
                                           'price': trans['mutual_fund']['unit_price']
                                       })
