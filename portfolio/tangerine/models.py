from django.db import models, transaction

import requests
import tangerine.tangerinelib
from dateutil import parser
from decimal import Decimal
import datetime
import arrow
import pandas

from finance.models import BaseAccount, BaseClient, BaseRawActivity, Security, SecurityPrice, Activity

class TangerineRawActivity(BaseRawActivity):
    day = models.DateField()
    description = models.CharField(max_length=1000)
    activity_id = models.CharField(max_length=32, unique=True)
    type = models.CharField(max_length=32)  
    security = models.ForeignKey(Security, on_delete=models.CASCADE, null=True)
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    
    def __str__(self):
        return '{}: Bought {} {} at {}'.format(self.day, self.qty, self.security, self.price)
    
    def __repr__(self):
        return 'TangerineRawActivity<{},{},{},{},{}>'.format(self.account, self.day, self.security, self.qty, self.price)

    def CreateActivity(self): 
        if self.type == 'PURCHASES':
            type = Activity.Type.Buy
        else:
            type = Activity.Type.Dividend
            
        return Activity(account=self.account, tradeDate=self.day, security=self.security, description=self.description, qty=self.qty, 
                        price=self.price, netAmount=0, type=Activity.Type.Buy, raw=self)
    
class TangerineAccount(BaseAccount):
    display_name = models.CharField(max_length = 100)
    account_balance = models.DecimalField(max_digits=16, decimal_places=6)
    
    def __str__(self):
        return self.display_name
            
    @property
    def cur_balance(self):
        return self.account_balance
    
class TangerineClient(BaseClient):
    username = models.CharField(max_length=32)
    password = models.CharField(max_length=100)
    securityq1 = models.CharField(max_length=1000)
    securitya1 = models.CharField(max_length=100)
    securityq2 = models.CharField(max_length=1000)
    securitya2 = models.CharField(max_length=100)
    securityq3 = models.CharField(max_length=1000)
    securitya3 = models.CharField(max_length=100)
        
    def __repr__(self):
        return 'TangerineClient<{}>'.format(self.display_name)
    
    @property
    def activitySyncDateRange(self):
        return 2000
    
    def _GetRequest(self, url, params={}):
        r = requests.get(url, params=params)
        r.raise_for_status()
        return r.json()
            
    def Authorize(self):
        secrets_dict = {'username':self.username, 'password':self.password, 
        'security_questions': {
            self.securityq1:self.securitya1,
            self.securityq2:self.securitya2,
            self.securityq3:self.securitya3} }
                
        secrets = tangerine.tangerinelib.DictionaryBasedSecretProvider(secrets_dict)
        self.client = tangerine.tangerinelib.TangerineClient(secrets)
        
    def SyncAccounts(self):
        with self.client.login():
            accounts = self.client.list_accounts()
            for a in accounts: 
                acc = self.accounts.get_or_create(id=a['number'], defaults={'type':a['description']})
             
    def _CreateRawActivities(self, account, start, end):
        with self.client.login():
            client.list_transactions([account.id], start.date(), end.date())
        end = end.replace(hour=0, minute=0, second=0)
        json = self._GetRequest('accounts/{}/activities'.format(account.id), {'startTime': start.isoformat(), 'endTime': end.isoformat()})
        print( "Get activities from source returned: " + simplejson.dumps(json))
        count = 0
        for activity_json in json['activities']:
            if TangerineRawActivity.Add(activity_json, account):
                count += 1
        return count