import csv
from decimal import Decimal

from dateutil import parser
from django.db import models

from finance.models import BaseAccount, BaseRawActivity, Activity, HoldingDetail
from securities.models import Security


class VirtBrokersRawActivity(BaseRawActivity):
    day = models.DateField()
    symbol = models.CharField(max_length=100, blank=True, default='')
    trans_id = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=1000, blank=True, default='')
    currency = models.CharField(max_length=100, blank=True, null=True)
    qty = models.DecimalField(max_digits=16, decimal_places=6, default=0)
    price = models.DecimalField(max_digits=16, decimal_places=6, default=0)
    net_amount = models.DecimalField(max_digits=16, decimal_places=2)
    commission = models.DecimalField(max_digits=16, decimal_places=2)
    type = models.CharField(max_length=100)

    def CreateActivity(self):
        if self.type == 'EFT':           self.type = Activity.Type.Deposit
        elif self.type == 'BUY':         self.type = Activity.Type.Buy
        elif self.type == 'SELL':        self.type = Activity.Type.Sell
        elif self.type == 'DIV':         self.type = Activity.Type.Dividend
        elif self.type == 'FXT':         self.type = Activity.Type.FX
        elif self.type == 'INT':         self.type = Activity.Type.Interest
        else:                            assert False, 'Unmapped activity type in Virtual Brokers'

        if self.type == Activity.Type.Dividend:
            # We expect qty and net_amount to be valid here
            self.price = self.net_amount / self.qty

        security = None
        if self.symbol:
            security, _ = Security.objects.get_or_create(symbol=self.symbol,
                                                         defaults={'currency': self.currency})

        Activity.objects.create(account=self.account, trade_date=self.day, security=security,
                                description=self.description, cash_id=self.currency, qty=self.qty,
                                price=self.price, net_amount=self.net_amount,
                                commission=self.commission, type=self.type, raw=self)

class VirtBrokersAccount(BaseAccount):
    activitySyncDateRange = 0

    def __str__(self):
        return self.display_name

    def __repr__(self):
        return 'VirtBrokersAccount<{},{},{}>'.format(self.display_name, self.account_id, self.type)

    def import_from_csv(self, csv_file):
        csv_file.open('r')
        fields = ['day', 'EffectiveDate', 'AccountNumber', 'trans_id', 'sub_trans_id', 'symbol', 'description',
                  'type', 'qty', 'commission', 'price', 'net_amount', 'SecurityType', 'currency', 'rep_cd']
        reader = csv.DictReader(csv_file, fieldnames=fields)
        for line in reader:
            try:
                line['day'] = parser.parse(line['day']).date()
            except:
                continue

            del line['EffectiveDate']
            del line['AccountNumber']
            line['trans_id'] = line['trans_id'] or 'sub-'+line['sub_trans_id']
            del line['sub_trans_id']
            del line['SecurityType']
            del line['rep_cd']

            line['qty'] = Decimal(line['qty']) if line['qty'] else 0
            line['price'] = Decimal(line['price']) if line['price'] else 0
            line['commission'] = -Decimal(line['commission']) if line['commission'] else 0
            line['net_amount'] = Decimal(line['net_amount']) if line['net_amount'] else 0

            VirtBrokersRawActivity.objects.get_or_create(account=self, **line)
