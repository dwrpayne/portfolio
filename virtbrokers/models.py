import csv
from dateutil import parser
from decimal import Decimal

from django.db import models
from finance.models import BaseAccount, BaseClient, BaseRawActivity, Activity
from securities.models import Security

class VirtBrokersRawActivity(BaseRawActivity):
    day = models.DateField()
    symbol = models.CharField(max_length=100, blank=True, default='')
    trans_id = models.CharField(max_length=100)
    description = models.CharField(max_length=1000, blank=True, default='')
    currency = models.CharField(max_length=100, blank=True, null=True)
    qty = models.DecimalField(max_digits=16, decimal_places=6, default=0)
    price = models.DecimalField(max_digits=16, decimal_places=6, default=0)
    netAmount = models.DecimalField(max_digits=16, decimal_places=2)
    commission = models.DecimalField(max_digits=16, decimal_places=2)
    type = models.CharField(max_length=100)

    def CreateActivity(self):
        if self.type == 'EFT':           self.type = Activity.Type.Deposit
        if self.type == 'BUY':           self.type = Activity.Type.Buy
        if self.type == 'SELL':          self.type = Activity.Type.Sell
        if self.type == 'DIV':           self.type = Activity.Type.Dividend
        if self.type == 'FXT':           self.type = Activity.Type.FX
        if self.type == 'INT':           self.type = Activity.Type.Interest

        # Todo: stocks shouldn't have .TO - that is datasource level only.
        if self.symbol in ['NDM', 'XAW']:
            self.symbol += '.TO'

        security = None
        if self.symbol:
            security, _ = Security.objects.get_or_create(symbol=self.symbol,
                                                         defaults={'currency': self.currency})

        Activity.objects.create(account=self.account, tradeDate=self.day, security=security,
                                description=self.description, cash_id=self.currency, qty=self.qty,
                                price=self.price, netAmount=self.netAmount,
                                commission=self.commission, type=self.type, raw=self)

class VirtBrokersAccount(BaseAccount):
    def __str__(self):
        return '{} {} {}'.format(self.client, self.id, self.type)

    def __repr__(self):
        return 'VirtBrokersAccount<{},{},{}>'.format(self.client, self.id, self.type)

    @property
    def activitySyncDateRange(self):
        return 0

    def import_csv(self, csv_file):
        with open(csv_file, newline='') as f:
            fields = ['day', 'EffectiveDate', 'AccountNumber', 'trans_id', 'sub_trans_id', 'symbol', 'description',
                      'type', 'qty', 'commission', 'price', 'netAmount', 'SecurityType', 'currency', 'rep_cd']
            reader = csv.DictReader(f, fieldnames=fields)
            for line in reader:
                try:
                    line['day'] = parser.parse(line['day']).date()
                except:
                    continue

                del line['EffectiveDate']
                del line['AccountNumber']
                line['trans_id'] = line['trans_id'] or line['sub_trans_id']
                del line['sub_trans_id']
                del line['SecurityType']
                del line['rep_cd']

                line['qty'] = Decimal(line['qty']) if line['qty'] else 0
                line['price'] = Decimal(line['price']) if line['price'] else 0
                line['commission'] = Decimal(line['commission']) if line['commission'] else 0
                line['netAmount'] = Decimal(line['netAmount']) if line['netAmount'] else 0

                VirtBrokersRawActivity.objects.create(account=self, **line)

    def ReImportActivities(self, csv_file):
        """
        Total hack for now.
        """
        # r'C:\Users\David\Dropbox\coding\portfolio\_private\sean_26386387.csv'
        VirtBrokersRawActivity.objects.filter(account=self).delete()
        self.import_csv(csv_file)
        self.RegenerateActivities()


class VirtBrokersClient(BaseClient):
    def __repr__(self):
        return 'VirtBrokersClient<{}>'.format(self.display_name)
