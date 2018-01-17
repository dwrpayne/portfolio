from decimal import Decimal

import requests
from bs4 import BeautifulSoup
import re
from more_itertools import split_before
from dateutil import parser
from django.db import models
import utils.dates

from finance.models import Activity, BaseAccount, BaseRawActivity
from securities.models import Security
from datasource.models import DataSourceMixin


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
        security, created = Security.mutualfunds.get_or_create(symbol=self.symbol,
                                           defaults={'currency':'CAD', 'datasource': None})
        if created:
            security.SetDataSource(GrsDataSource.objects.get_or_create(symbol=self.symbol))

        total_cost = self.qty * self.price
        Activity.objects.create_with_deposit(account=self.account, tradeDate=self.day, security=security,
                                cash_id=security.currency,
                                description=self.description, qty=self.qty, raw=self,
                                price=self.price, netAmount=-total_cost, type=Activity.Type.Buy)


class GrsClient(models.Model):
    username = models.CharField(max_length=32)
    password = models.CharField(max_length=100)

    def __str__(self):
        return self.username

    def __repr__(self):
        return 'GrsClient<{}>'.format(self.username)

    def __enter__(self):
        self.session = requests.Session()
        response = self.session.post('https://ssl.grsaccess.com/Information/login.aspx',
                                     data={'username': self.username, 'password': self.password})
        response.raise_for_status()
        return self

    def __exit__(self, type, value, traceback):
        self.session.close()

    def PrepareRateRetrieval(self, plan_data):
        self.session.get('https://ssl.grsaccess.com/common/list_item_selection.aspx',
                         params={'Selected_Info': plan_data})

    def GetRates(self, symbol, start, end):
        response = self.session.post('https://ssl.grsaccess.com/english/member/NUV_Rates_Details.aspx',
                                     data={'PlanFund': symbol,
                                           'StartDate': start.format('%m/%d/%y'),
                                           'EndDate': end.format('%m/%d/%y')
                                           })
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        table_header = soup.find('tr', 'table-header')
        if not table_header:
            return []
        dates = (td.string for td in table_header('td')[1:])
        values = (td.string for td in table_header.next_sibling('td')[1:])
        rates = [(parser.parse(date).date(), Decimal(value.strip('$')))
                 for date, value in zip(dates, values)
                 if 'Unknown' not in value]
        return rates

    def GetActivities(self, account, start, end):
        response = self.session.post(
            'https://ssl.grsaccess.com/english/member/activity_reports_details.aspx',
            data={
                'MbrPlanId': account.id, 'txtEffStartDate': start.format('MM/DD/YYYY'),
                'txtEffEndDate': end.format('MM/DD/YYYY'), 'Submit': 'Submit'
            }
        )
        response.raise_for_status()

        """
        Activities are returned in an html table, with the first few rows being headers.
        Example activity row:
        <TR>
            <TD class='activities-d-lit1'>01-FEB-17</TD>
            <TD class='activities-d-lit2'>New contribution</TD>
            <TD class='activities-d-transamt'>123.45</TD>
            <TD class='activities-d-netunitvalamt'>22.123456</TD>
            <TD class='activities-d-unitnum'>5.58005</TD>
        </TR>
        """
        soup = BeautifulSoup(response.text, 'html.parser')
        tags = soup.find_all(class_=re.compile('activities-d-*'))
        if not tags:
            return []

        for activity_list in split_before(tags, lambda tag: tag.attrs['class'][0] == tags[0].attrs['class'][0]):
            yield [a.text for a in activity_list]


class GrsAccount(BaseAccount):
    client = models.ForeignKey(GrsClient, on_delete=models.DO_NOTHING, null=True, blank=True)
    activitySyncDateRange = 360

    def __str__(self):
        return '{} {} {}'.format(self.client, self.id, self.type)

    def __repr__(self):
        return 'GrsAccount<{},{},{}>'.format(self.client, self.id, self.type)

    def CreateActivities(self, start, end):
        with self.client as client:
            for day, desc, _, price, qty in client.GetActivities(self, start, end):
                # TODO: Hacking the symbol here to the only one I buy. I have the description in
                # TODO: <TD class='activities-sh2'>Canadian Equity (Leith Wheeler)-Employer</TD>
                # TODO: Create the security with that description and then do a lookup here.
                GrsRawActivity.objects.create(
                    account=self, day=parser.parse(day).date(),
                    qty=Decimal(qty), price=Decimal(price),
                    symbol='ETP', description=desc)


class GrsDataSource(DataSourceMixin):
    symbol = models.CharField(max_length=32)
    client = models.ForeignKey(GrsClient, on_delete=models.CASCADE)
    plan_data = models.CharField(max_length=100)
    MAX_SYNC_DAYS = 15

    def __str__(self):
        return "GRS Client {} for symbol {}".format(self.client, self.symbol)

    def __repr__(self):
        return "GrsDataSource<{},{}>".format(self.symbol, self.client)

    def _Retrieve(self, start, end):
        with self.client as client:
            client.PrepareRateRetrieval(self.plan_data)
            for period in utils.dates.day_intervals(self.MAX_SYNC_DAYS, start, end):
                yield from client.GetRates(self.symbol, period.start, period.end)
