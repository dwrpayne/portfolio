from decimal import Decimal

import requests
from bs4 import BeautifulSoup
import re
from more_itertools import split_before
from dateutil import parser
from django.db import models, transaction
import utils

from finance.models import Activity, BaseAccount, BaseClient, BaseRawActivity
from securities.models import Security
from datasource.models import DataSourceMixin
from polymorphic.manager import PolymorphicManager


class GrsRawActivityManager(PolymorphicManager):
    def create_from_html(self, html, account):
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
        soup = BeautifulSoup(html, 'html.parser')
        tags = soup.find_all(class_=re.compile('activities-d-*'))
        if not tags:
            return

        rows = split_before(tags, lambda tag: tag.class_ == tags[0].class_)
        with transaction.atomic():
            for day, desc, _, price, qty in rows:
                # TODO: Hacking the symbol here to the only one I buy. I have the description in
                # TODO: <TD class='activities-sh2'>Canadian Equity (Leith Wheeler)-Employer</TD>
                # TODO: Create the security with that description and then do a lookup here.
                self.create(
                    account=account, day=parser.parse(day).date(),
                    qty=Decimal(qty), price=Decimal(price),
                    symbol='ETP', description=desc)
        return len(rows)


class GrsRawActivity(BaseRawActivity):
    day = models.DateField()
    symbol = models.CharField(max_length=100)
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    description = models.CharField(max_length=256)

    objects = GrsRawActivityManager()

    def __str__(self):
        return '{}: Bought {} {} at {}'.format(self.day, self.qty, self.symbol, self.price)

    def __repr__(self):
        return 'GrsRawActivity<{},{},{},{},{}>'.format(self.account, self.day, self.symbol, self.qty, self.price)

    def CreateActivity(self):
        try:
            security = Security.mutualfunds.get(symbol=self.symbol)
        except Security.DoesNotExist:
            datasource = GrsDataSource.objects.get_or_create(symbol=self.symbol)
            security = Security.mutualfunds.Create(self.symbol, 'CAD', datasource=datasource)

        total_cost = self.qty * self.price

        Activity.objects.create_with_deposit(account=self.account, tradeDate=self.day, security=security,
                                cash_id=security.currency,
                                description=self.description, qty=self.qty, raw=self,
                                price=self.price, netAmount=-total_cost, type=Activity.Type.Buy)


class GrsAccount(BaseAccount):
    """
    We don't really need this class here, but GRS is a good example of a
    simple integration and I want it to be complete
    """
    def __str__(self):
        return '{} {} {}'.format(self.client, self.id, self.type)

    def __repr__(self):
        return 'GrsAccount<{},{},{}>'.format(self.client, self.id, self.type)

    @property
    def activitySyncDateRange(self):
        return 360

    def CreateRawActivities(self):
        with self.client as c:
            c.PrepareRateRetrieval()
            c.GetRawActivities()

        GrsRawActivity.objects.create_from_html(response.text, account)
        pass


class GrsClient(BaseClient):
    username = models.CharField(max_length=32)
    password = models.CharField(max_length=100)

    def __repr__(self):
        return 'GrsClient<{}>'.format(self.display_name)

    def Authorize(self):
        self.session = requests.Session()
        response = self.session.post('https://ssl.grsaccess.com/Information/login.aspx',
                          data={'username': self.username, 'password': self.password})
        response.raise_for_status()

    def CloseSession(self):
        self.session.close()

    def PrepareRateRetrieval(self, plan_data):
        self.session.get('https://ssl.grsaccess.com/common/list_item_selection.aspx',
                           params={'Selected_Info': plan_data})

    def RequestRates(self, symbol, start, end):
        response = self.session.post('https://ssl.grsaccess.com/english/member/NUV_Rates_Details.aspx',
                                   data={'PlanFund': symbol,
                                         'StartDate': start.format('MM/DD/YYYY'),
                                         'EndDate': end.format('MM/DD/YYYY'), }
                                )
        response.raise_for_status()
        return response

    def GetRawActivities(self, id, start, end):
        response = self.session.post(
            'https://ssl.grsaccess.com/english/member/activity_reports_details.aspx',
            data={
                'MbrPlanId': id, 'txtEffStartDate': start.format('MM/DD/YYYY'),
                'txtEffEndDate': end.format('MM/DD/YYYY'), 'Submit': 'Submit'
            }
        )
        GrsRawActivity.objects.create_from_html(response.text, account)
        response.raise_for_status()
        return response.text


class GrsDataSource(DataSourceMixin):
    symbol = models.CharField(max_length=32)
    client = models.ForeignKey(GrsClient, on_delete=models.CASCADE)
    plan_data = models.CharField(max_length=100)

    @property
    def max_sync_days(self):
        return 15

    def _Retrieve(self, start, end):
        with self.client as client:
            client.PrepareRateRetrieval(self.plan_data)
            for s, e in utils.dates.day_intervals(self.max_sync_days, start, end):
                response = client.RequestRates(self.symbol, s, e)

                soup = BeautifulSoup(response.text, 'html.parser')
                table_header = soup.find('tr', 'table-header')
                if table_header:
                    dates = (td.string for td in table_header('td')[1:])
                    values = (td.string for td in table_header.next_sibling('td')[1:])
                    for date, value in zip(dates, values):
                        if 'Unknown' not in value:
                            yield parser.parse(date).date(), Decimal(value.strip('$'))
        return
