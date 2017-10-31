from django.db import models, transaction
from django import forms

import requests
from bs4 import BeautifulSoup
from dateutil import parser
from decimal import Decimal
import datetime
import arrow
import pandas

from finance.models import BaseAccount, BaseClient, BaseRawActivity, Security, SecurityPrice, Activity

class GrsRawActivity(BaseRawActivity):
    day = models.DateField()
    security = models.ForeignKey(Security, on_delete=models.CASCADE, null=True)
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)

    def __str__(self):
        return '{}: Bought {} {} at {}'.format(self.day, self.qty, self.security, self.price)
    
    def __repr__(self):
        return 'GrsRawActivity<{}>'.format(self.username)

    def CreateActivity(self): 
        return Activity(account=self.account, tradeDate=self.day, security=self.security, description='', qty=self.qty, 
                        price=self.price, netAmount=0, type=Activity.Type.Buy, raw=self)
    
class GrsAccount(BaseAccount):
    plan_data = models.CharField(max_length=100)    
    
class GrsClient(BaseClient):
    password = models.CharField(max_length=100)
    
    def __repr__(self):
        return 'GrsClient<{}>'.format(self.username)
    
    @property
    def activitySyncDateRange(self):
        return 360

    @classmethod 
    def Create(cls, username, password, plan_data, plan_id):
        client = GrsClient(username = username, password=password, plan_data=plan_data, plan_id=plan_id)
        client.save()
        client.Authorize()
        return client
            
    def Authorize(self):
        self.session = requests.Session()
        self.session.post('https://ssl.grsaccess.com/Information/login.aspx', data={'username': self.username, 'password': self.password})         
        
    def CloseSession(self):
        self.session.close()

    def _CreateRawActivities(self, account_id, start, end):
        response = self.session.post('https://ssl.grsaccess.com/english/member/activity_reports_details.aspx', data={'MbrPlanId':account_id, 'txtEffStartDate': start.format('MM/DD/YYYY'), 'txtEffEndDate': end.format('MM/DD/YYYY'), 'Submit':'Submit'})
        soup = BeautifulSoup(response.text, 'html.parser')
        trans_dates = [parser.parse(tag.contents[0]).date() for tag in soup.find_all('td', class_='activities-d-lit1')]    
        units = [Decimal(tag.contents[0]) for tag in soup.find_all('td', class_='activities-d-unitnum')]
        prices = [Decimal(tag.contents[0]) for tag in soup.find_all('td', class_='activities-d-netunitvalamt')]
        with transaction.atomic():
            for day, qty, price in zip(trans_dates, units, prices):
                GrsRawActivity.objects.create(account_id=account_id, day=day, qty=qty, price=price, security_id='ETP')

    def _GetRawPrices(self, symbol, start, end):
        response = self.session.post('https://ssl.grsaccess.com/english/member/NUV_Rates_Details.aspx', 
            data={'PlanFund': symbol, 'PlanDetail':'', 'BodyTitle':'', 
                'StartDate': start.format('MM/DD/YYYY'), 'EndDate': end.format('MM/DD/YYYY'), 'Submit':'Submit'},
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 6.0; WOW64; rv:24.0) Gecko/20100101 Firefox/24.0' }
            )
        soup = BeautifulSoup(response.text, 'html.parser')
        table_header = soup.find('tr', class_='table-header')
        if not table_header: return []
        dates = [tag.contents[0] for tag in table_header.find_all('td')[1:]]
        values = [tag.contents[0] for tag in soup.find('tr', class_='body-text').find_all('td')[1:]]
        return zip(dates, values)


    def _SyncPrices(self, start_date=arrow.get('2010-07-01'), end_date=arrow.now()):
        self.session.get('https://ssl.grsaccess.com/common/list_item_selection.aspx', params={'Selected_Info': self.accounts.all()[0].plan_data})
        for security in Security.objects.filter(type=Security.Type.MutualFund):
            start_date = max(start_date, arrow.get(security.GetLatestEntryDate() + datetime.timedelta(days=1)))
            date_range = arrow.Arrow.interval('day', start_date, end_date, 15)
            print('{} requests'.format(len(date_range)), end='')
            data = []
            for start, end in date_range:
                print('.',end='', flush=True)
                try:
                    data += self._GetRawPrices(security.symbol, start, end)
                except requests.exceptions.ConnectionError:
                    pass

            print()         

            cleaned_data = {parser.parse(date).date(): Decimal(value[1:]) for date, value in data if not 'Unknown' in value}

            series = pandas.Series(cleaned_data)
            index = pandas.DatetimeIndex(start = min(series.index), end=max(series.index), freq='D').date    
            series = series.reindex(index).ffill()

            security.rates.bulk_create([SecurityPrice(security=security, day=day, price=price) for day, price in series.iteritems()])

