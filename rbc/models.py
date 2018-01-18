import csv
from dateutil import parser
from decimal import Decimal

from django.db import models
from finance.models import BaseAccount, BaseRawActivity, Activity
from securities.models import Security

class RbcRawActivity(BaseRawActivity):
    day = models.DateField()
    symbol = models.CharField(max_length=100, blank=True, default='')
    description = models.CharField(max_length=1000, blank=True, default='')
    currency = models.CharField(max_length=100, blank=True, null=True)
    qty = models.DecimalField(max_digits=16, decimal_places=6, default=0)
    price = models.DecimalField(max_digits=16, decimal_places=6, default=0)
    netAmount = models.DecimalField(max_digits=16, decimal_places=2)
    type = models.CharField(max_length=100)

    def CreateActivity(self):

        if self.type == 'Deposits & Contributions':          self.type = 'Deposit'
        if self.type == 'Withdrawals & De-registrations':    self.type = 'Withdrawal'
        if self.type == 'Dividends':                         self.type = 'Dividend'
        if self.type == 'Return of Capital':                 self.type = 'RetCapital'
        if self.type == 'Transfers':                         self.type = 'FX'

        # DRIP transaction special case
        if self.type == 'Dividend' and float(self.netAmount) < 0 and self.qty:
            self.type = 'Buy'
            self.price = Decimal(self.description.split('REINV@')[1].split()[0].split('$')[1])

        # Todo: stocks shouldn't have .TO - that is datasource level only.
        if self.symbol in ['VCN', 'VFV', 'VDY', 'VDU']:
            self.symbol += '.TO'

        security = None
        if self.symbol:
            security, _ = Security.objects.get_or_create(symbol=self.symbol,
                                                         defaults={'currency': self.currency})

        # Handle transactions settling in base currency
        # TODO: This is broken if the security was just created - we assume it's the base currency.
        # TODO: How to fix?
        if 'EXCHANGE RATE' in self.description:
            print (self.description)
            rate = Decimal(self.description.split()[-1])
            settle_currency = self.currency
            self.currency = security.currency

            settle_amount = self.netAmount
            self.netAmount /= rate

            Activity.objects.create_fx(to_currency=self.currency, to_amount=-self.netAmount,
                                       from_currency=settle_currency, from_amount=settle_amount,
                                       account=self.account, tradeDate=self.day, security=security,
                                       description='Autogenerated FX transaction for trade settling in other currency @ Rate {}%'.format(rate),
                                       qty=0, price=0, raw=self)

        commission = 0
        if self.type in [Activity.Type.Buy, Activity.Type.Sell]:
            commission = self.qty * self.price + self.netAmount


        Activity.objects.create(account=self.account, tradeDate=self.day, security=security,
                                description=self.description, cash_id=self.currency, qty=self.qty,
                                price=self.price, netAmount=self.netAmount,
                                commission=commission, type=self.type, raw=self)


class RbcAccount(BaseAccount):
    activitySyncDateRange = 0

    def __str__(self):
        self.display_name

    def __repr__(self):
        return 'RbcAccount<{},{},{}>'.format(self.display_name, self.id, self.type)

    def import_from_csv(self, csv_file):
        csv_file.open('r')
        fields = ['day', 'type', 'symbol', 'qty', 'price', 'SettlementDate', 'Account', 'netAmount', 'currency', 'description']
        reader = csv.DictReader(csv_file, fieldnames=fields)
        for line in reader:
            try:
                line['day'] = parser.parse(line['day']).date()
            except:
                continue

            del line['SettlementDate']
            del line['Account']

            line['qty'] = Decimal(line['qty']) if line['qty'] else 0
            line['price'] = Decimal(line['price']) if line['price'] else 0
            line['netAmount'] = Decimal(line['netAmount']) if line['netAmount'] else 0

            RbcRawActivity.objects.get_or_create(account=self, **line)
