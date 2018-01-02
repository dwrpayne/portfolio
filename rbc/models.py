import csv
import pendulum
from django.db import models
from finance.models import BaseAccount, BaseClient, BaseRawActivity


class RbcRawActivity(BaseRawActivity):
    day = models.DateField()
    type = models.CharField(max_length=32)
    symbol = models.CharField(max_length=100)
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    total_amount = models.DecimalField(max_digits=16, decimal_places=6)
    currency = models.CharField(max_length=32)
    description = models.CharField(max_length=1000)


class RbcAccount(BaseAccount):
    def __str__(self):
        return '{} {} {}'.format(self.client, self.id, self.type)

    def __repr__(self):
        return 'RbcAccount<{},{},{}>'.format(self.client, self.id, self.type)

    @property
    def activitySyncDateRange(self):
        return 0

    def import_csv(self, csv_file):
        with open(csv_file, newline='') as f:
            fields = ['day', 'type', 'symbol', 'qty', 'price', 'Settlement Date', 'Account', 'total_amount', 'currency', 'description']
            reader = csv.DictReader(f, fieldnames=fields)
            for line in reader:
                try:
                    fields['day'] = pendulum.parse(fields['day'])
                except pendulum.ParserError:
                    continue








class RbcClient(BaseClient):
    def __repr__(self):
        return 'RbcClient<{}>'.format(self.display_name)
