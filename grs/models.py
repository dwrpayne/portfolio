from decimal import Decimal

import arrow
import requests
from bs4 import BeautifulSoup
from dateutil import parser
from django.db import models, transaction

from finance.models import Activity, BaseAccount, BaseClient, BaseRawActivity
from securities.models import Security


class GrsRawActivity(BaseRawActivity):
    day = models.DateField()
    symbol = models.CharField(max_length=100)
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    description = models.CharField(max_length=256)

    def __str__(self):
        return '{}: Bought {} {} at {}'.format(self.day, self.qty, self.symbol, self.price)

    def __repr__(self):
        return 'GrsRawActivity<{},{},{},{},{}>'.format(self.account, self.day, self.symbol, self.qty, self.price)

    def CreateActivity(self):
        try:
            security = Security.mutualfunds.get(symbol=self.symbol)
        except:
            security = Security.mutualfunds.Create(self.symbol, 'CAD')

        total_cost = self.qty * self.price

        Activity.objects.create(account=self.account, tradeDate=self.day, security=None,
                                cash_id=security.currency.code + ' Cash',
                                description='Generated Deposit', qty=0, raw=self,
                                price=0, netAmount=total_cost, type=Activity.Type.Deposit)

        Activity.objects.create(account=self.account, tradeDate=self.day, security=security,
                                cash_id=security.currency.code + ' Cash',
                                description=self.description, qty=self.qty, raw=self,
                                price=self.price, netAmount=-total_cost, type=Activity.Type.Buy)


class GrsAccount(BaseAccount):
    plan_data = models.CharField(max_length=100)

    def __str__(self):
        return '{} {} {}'.format(self.client, self.id, self.type)

    def __repr__(self):
        return 'GrsAccount<{},{},{}>'.format(self.client, self.id, self.type)


class GrsClient(BaseClient):
    username = models.CharField(max_length=32)
    password = models.CharField(max_length=100)

    def __repr__(self):
        return 'GrsClient<{}>'.format(self.display_name)

    @property
    def activitySyncDateRange(self):
        return 360

    def Authorize(self):
        self.session = requests.Session()
        self.session.post('https://ssl.grsaccess.com/Information/login.aspx',
                          data={'username': self.username, 'password': self.password})

    def CloseSession(self):
        self.session.close()

    def _CreateRawActivities(self, account, start, end):
        response = self.session.post('https://ssl.grsaccess.com/english/member/activity_reports_details.aspx', data={
            'MbrPlanId': account.id, 'txtEffStartDate': start.format('MM/DD/YYYY'),
            'txtEffEndDate': end.format('MM/DD/YYYY'), 'Submit': 'Submit'})
        soup = BeautifulSoup(response.text, 'html.parser')
        trans_dates = [parser.parse(tag.contents[0]).date()
                       for tag in soup.find_all('td', class_='activities-d-lit1')]
        descriptions = [tag.contents[0]
                        for tag in soup.find_all('td', class_='activities-d-lit2')]
        units = [Decimal(tag.contents[0])
                 for tag in soup.find_all('td', class_='activities-d-unitnum')]
        prices = [Decimal(tag.contents[0])
                  for tag in soup.find_all('td', class_='activities-d-netunitvalamt')]
        count = 0
        with transaction.atomic():
            for day, qty, price, desc in zip(trans_dates, units, prices, descriptions):
                GrsRawActivity.objects.create(
                    account=account, day=day, qty=qty, price=price, symbol='ETP', description=desc)
                count += 1
        return count

    def _GetRawPrices(self, lookup, start_date, end_date):
        print("_GetRawPrices... {} {} {}".format(lookup.lookupSymbol, start_date, end_date))
        for start, end in arrow.Arrow.interval('day', arrow.get(start_date), arrow.get(end_date), 15):
            response = self.session.post('https://ssl.grsaccess.com/english/member/NUV_Rates_Details.aspx',
                                         data={'PlanFund': lookup.lookupSymbol, 'PlanDetail': '', 'BodyTitle': '',
                                               'StartDate': start.format('MM/DD/YYYY'),
                                               'EndDate': end.format('MM/DD/YYYY'), 'Submit': 'Submit'},
                                         headers={
                                             'User-Agent': 'Mozilla/5.0 (Windows NT 6.0; WOW64; rv:24.0) Gecko/20100101 Firefox/24.0'}
                                         )
            soup = BeautifulSoup(response.text, 'html.parser')
            table_header = soup.find('tr', class_='table-header')
            if table_header:
                dates = [tag.contents[0] for tag in table_header.find_all('td')[1:]]
                values = [tag.contents[0]
                          for tag in soup.find('tr', class_='body-text').find_all('td')[1:]]
                for date, value in zip(dates, values):
                    if 'Unknown' not in value:
                        yield parser.parse(date).date(), Decimal(value[1:])
        return

    def SyncPrices(self):
        self.session.get('https://ssl.grsaccess.com/common/list_item_selection.aspx',
                         params={'Selected_Info': self.accounts.first().plan_data})
        for security in self.currentSecurities:
            security.SyncRates()
