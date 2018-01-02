import csv
import pendulum
from decimal import Decimal
from finance.models import BaseAccount, BaseClient, ManualRawActivity


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
            fields = ['day', 'type', 'symbol', 'qty', 'price', 'SettlementDate', 'Account', 'netAmount', 'currency', 'description']
            reader = csv.DictReader(f, fieldnames=fields)
            for line in reader:
                try:
                    line['day'] = pendulum.from_format(line['day'], '%d-%b-%y').date()
                except:# pendulum.exceptions.ParserError:
                    continue

                del line['SettlementDate']
                del line['Account']

                if line['type'] == 'Deposits & Contributions': line['type'] = 'Deposit'
                if line['type'] == 'Dividends': line['type'] = 'Dividend'
                if line['type'] == 'Transfers': line['type'] = 'FX'

                line['qty'] = Decimal(line['qty']) if line['qty'] else 0
                line['price'] = Decimal(line['price']) if line['price'] else 0
                line['netAmount'] = Decimal(line['netAmount']) if line['netAmount'] else 0

                if line['symbol'] in ['VCN', 'VFV']: line['symbol'] += '.TO'

                ManualRawActivity.objects.create(account=self, **line)

    def CreateActivities(self, start, end):
        """
        Total hack for now.
        """
        self.rawactivities.all().delete()
        self.import_csv(r'C:\Users\David\Dropbox\coding\portfolio\_private\emilyrbc.csv')
        self._RegenerateHoldings()


class RbcClient(BaseClient):
    def __repr__(self):
        return 'RbcClient<{}>'.format(self.display_name)
