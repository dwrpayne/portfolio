from django.db import models, transaction

import requests
from bs4 import BeautifulSoup
from dateutil import parser
from decimal import Decimal
import datetime
import arrow
import pandas
from utils.api import api_response

from finance.models import BaseAccount, BaseClient, BaseRawActivity, Security, SecurityPrice, Activity

class GrsRawActivity(BaseRawActivity):
    day = models.DateField()
    security = models.ForeignKey(Security, on_delete=models.CASCADE, null=True)
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)

    class Meta:        
        unique_together = ('baserawactivity_ptr', 'day', 'security', 'qty', 'price')

    def __str__(self):
        return '{}: Bought {} {} at {}'.format(self.day, self.qty, self.security, self.price)
    
    def __repr__(self):
        return 'GrsRawActivity<{},{},{},{},{}>'.format(self.account, self.day, self.security, self.qty, self.price)

    def CreateActivity(self): 
        return Activity(account=self.account, tradeDate=self.day, security=self.security, description='', qty=self.qty, 
                        price=self.price, netAmount=0, type=Activity.Type.Buy, raw=self)
    
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
        self.session.post('https://ssl.grsaccess.com/Information/login.aspx', data={'username': self.username, 'password': self.password})         
        
    def CloseSession(self):
        self.session.close()

    def _CreateRawActivities(self, account, start, end):
        response = self.session.post('https://ssl.grsaccess.com/english/member/activity_reports_details.aspx', data={'MbrPlanId':account.id, 'txtEffStartDate': start.format('MM/DD/YYYY'), 'txtEffEndDate': end.format('MM/DD/YYYY'), 'Submit':'Submit'})
        soup = BeautifulSoup(response.text, 'html.parser')
        trans_dates = [parser.parse(tag.contents[0]).date() for tag in soup.find_all('td', class_='activities-d-lit1')]    
        units = [Decimal(tag.contents[0]) for tag in soup.find_all('td', class_='activities-d-unitnum')]
        prices = [Decimal(tag.contents[0]) for tag in soup.find_all('td', class_='activities-d-netunitvalamt')]
        count = 0
        with transaction.atomic():
            for day, qty, price in zip(trans_dates, units, prices):
                obj, created = GrsRawActivity.objects.get_or_create(account=account, day=day, qty=qty, price=price, security_id='ETP')
                if created: count += 1
        return count


    def _GetRawPrices(self, lookup, start_date, end_date):
        print("_GetRawPrices... {} {} {}".format(lookup.lookupSymbol, start_date, end_date))
        for start, end in arrow.Arrow.interval('day', arrow.get(start_date), arrow.get(end_date), 15):
            response = self.session.post('https://ssl.grsaccess.com/english/member/NUV_Rates_Details.aspx', 
                data={'PlanFund': lookup.lookupSymbol, 'PlanDetail':'', 'BodyTitle':'', 
                    'StartDate': start.format('MM/DD/YYYY'), 'EndDate': end.format('MM/DD/YYYY'), 'Submit':'Submit'},
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 6.0; WOW64; rv:24.0) Gecko/20100101 Firefox/24.0' }
                )
            soup = BeautifulSoup(response.text, 'html.parser')
            table_header = soup.find('tr', class_='table-header')
            if table_header: 
                dates = [tag.contents[0] for tag in table_header.find_all('td')[1:]]
                values = [tag.contents[0] for tag in soup.find('tr', class_='body-text').find_all('td')[1:]]
                for date, value in zip(dates, values):
                    if not 'Unknown' in value:
                        yield parser.parse(date).date(), Decimal(value[1:])
        return 
    
    def SyncPrices(self):
        self.session.get('https://ssl.grsaccess.com/common/list_item_selection.aspx', params={'Selected_Info': self.accounts.first().plan_data})
        for security in self.currentSecurities:
            security.SyncRates(self._GetRawPrices)
