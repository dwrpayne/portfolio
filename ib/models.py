import csv
from decimal import Decimal

from dateutil import parser
from django.db import models

from finance.models import BaseAccount, BaseRawActivity, Activity, HoldingDetail
from securities.models import Security


class IbRawActivity(BaseRawActivity):
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
        security = None
        if self.symbol:
            security, _ = Security.objects.get_or_create(symbol=self.symbol,
                                                         defaults={'currency': self.currency})

        if self.type == Activity.Type.FX:
            to_currency, from_currency = self.symbol.split('.')
            Activity.objects.create_fx(to_currency=to_currency, to_amount=self.qty,
                                       from_currency=from_currency, from_amount=-self.net_amount,
                                       account=self.account, trade_date=self.day, security=None,
                                       description='Autogenerated FX transaction for trade settling in other currency @ Rate {}%'.format(self.price),
                                       qty=0, price=0, raw=self)
        else:
            Activity.objects.create(account=self.account, trade_date=self.day, security=security,
                                    description=self.description, cash_id=self.currency, qty=self.qty,
                                    price=self.price, net_amount=self.net_amount,
                                    commission=self.commission, type=self.type, raw=self)


class IbAccount(BaseAccount):
    activitySyncDateRange = 0

    def __str__(self):
        return self.display_name

    def __repr__(self):
        return 'IbAccount<{},{},{}>'.format(self.display_name, self.account_id, self.type)

    def import_from_csv(self, csv_file):
        csv_file.open('r')
        reader = csv.reader(csv_file)
        for rowtype, transtype, *line in reader:
            if rowtype == 'HEADER':
                pass
            else: # rowtype is DATA
                activity_params = {}
                price = 0
                qty = 0
                activity_params['commission'] = 0
                if transtype == 'TRFR':
                    accountid, trans_id, date, symbol, qty, price, currency, fxrate, _, net_amount, desc = line

                elif transtype == 'TRNT':
                    accountid, trans_id, date, symbol, buysell, currency, fxrate, qty, price, total_amount, commission, commissioncurrency, net_amount, desc = line
                    commission = Decimal(commission) if commission else 0
                    fxrate = Decimal(fxrate) if fxrate else 0
                    activity_params['commission'] = commission * fxrate
                    if not net_amount or Decimal(net_amount) == 0:
                        net_amount = Decimal(total_amount) + commission

                elif transtype == 'CTRN':
                    accountid, trans_id, date, transsubtype, symbol, net_amount, currency, fxrate, desc = line

                if accountid != self.account_id:
                    continue

                try:
                    activity_params['day'] = parser.parse(date).date()
                except:
                    continue

                if len(symbol) < 8:
                    symbol = symbol.replace(' ', '.') # Fix for 'BRK B'
                if symbol == '--':
                    symbol = ''

                activity_params['trans_id'] = trans_id
                activity_params['description'] = desc
                activity_params['symbol'] = symbol
                activity_params['currency'] = currency
                activity_params['qty'] = Decimal(qty) if qty else 0
                activity_params['price'] = Decimal(price) if price else 0
                activity_params['net_amount'] = Decimal(net_amount) if net_amount else 0

                # Options need to be fixed for lot price
                if len(symbol) > 10:
                    activity_params['price'] *= 100

                if transtype == 'CTRN' and transsubtype == 'Deposits/Withdrawals':
                    if activity_params['net_amount'] > 0:
                        activity_params['type'] = Activity.Type.Deposit
                    else:
                        activity_params['type'] = Activity.Type.Withdrawal
                elif transtype == 'TRNT' and buysell == 'BUY' and symbol == 'USD.CAD':
                    activity_params['type'] = Activity.Type.FX
                elif transtype == 'TRNT' and buysell == 'BUY':
                    activity_params['type'] = Activity.Type.Buy
                elif transtype == 'TRNT' and buysell == 'SELL':
                    activity_params['type'] = Activity.Type.Sell
                elif transtype == 'TRFR':
                    activity_params['type'] = Activity.Type.Transfer
                else:
                    assert False, 'Unmapped activity type in Interactive Brokers: ' + str(line)

                IbRawActivity.objects.get_or_create(account=self, **activity_params)
