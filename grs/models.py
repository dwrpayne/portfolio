from decimal import Decimal

import arrow
import requests
from bs4 import BeautifulSoup
from dateutil import parser
from django.db import models, transaction

from finance.models import Activity, BaseAccount, BaseClient, BaseRawActivity
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
        try:
            security = Security.mutualfunds.get(symbol=self.symbol)
        except Security.DoesNotExist:
            datasource = GrsDataSource.objects.get_or_create(symbol=self.symbol)
            security = Security.mutualfunds.Create(self.symbol, 'CAD', datasource=datasource)

        total_cost = self.qty * self.price

        Activity.objects.create_with_deposit(account=self.account, tradeDate=self.day, security=security,
                                cash_id=security.currency_id,
                                description=self.description, qty=self.qty, raw=self,
                                price=self.price, netAmount=-total_cost, type=Activity.Type.Buy)


class GrsAccount(BaseAccount):
    plan_data = models.CharField(max_length=100)

    def __str__(self):
        return '{} {} {}'.format(self.client, self.id, self.type)

    def __repr__(self):
        return 'GrsAccount<{},{},{}>'.format(self.client, self.id, self.type)

    def CreateActivitiesFromHtml(self, html):
        soup = BeautifulSoup(html, 'html.parser')
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
                    account=self, day=day, qty=qty, price=price, symbol='ETP', description=desc)
                count += 1
        return count


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
        return account.CreateActivitiesFromHtml(response.text)


class GrsDataSource(DataSourceMixin):
    symbol = models.CharField(max_length=32)
    client = models.ForeignKey(GrsClient, null=True, default=None)

    def _Retrieve(self, start, end):
        with self.client as client:
            client.session.get('https://ssl.grsaccess.com/common/list_item_selection.aspx',
                             params={'Selected_Info': client.accounts.first().plan_data})
            for s, e in arrow.Arrow.interval('day', arrow.get(start), arrow.get(end), client.activitySyncDateRange):
                response = client.session.post('https://ssl.grsaccess.com/english/member/NUV_Rates_Details.aspx',
                                             data={'PlanFund': self.symbol, 'PlanDetail': '', 'BodyTitle': '',
                                                   'StartDate': s.format('MM/DD/YYYY'),
                                                   'EndDate': e.format('MM/DD/YYYY'), 'Submit': 'Submit'},
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
