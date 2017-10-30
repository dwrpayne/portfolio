from django.db import models
from django import forms

# Create your models here.

class Client(models.Model):
    username = models.CharField(max_length=7, primary_key=True)
    password = forms.CharField(widget=forms.PasswordInput)
    plan_data = forms.CharField(max_length=100)



    refresh_token = models.CharField(max_length=100)
    access_token = models.CharField(max_length=100, null=True, blank=True)
    api_server = models.CharField(max_length=100, null=True, blank=True)
    token_expiry = models.DateTimeField(null=True, blank=True)
    authorization_lock = threading.Lock()

    @classmethod 
    def CreateClient(cls, username, refresh_token):
        client = Client(username = username, refresh_token = refresh_token)
        client.Authorize()
        client.SyncAccounts()
        return client
    
    @classmethod 
    def Get(cls, username):
        client = Client.objects.get(username=username)
        client.Authorize()
        return client

    def __str__(self):
        return self.username

    def __enter__(self):
        self.Authorize()
        return self

    def __exit__(self, type, value, traceback):
        self.CloseSession()     
        
    @property
    def needs_refresh(self):
        if not self.token_expiry: return True
        if not self.access_token: return True
        return self.token_expiry < (timezone.now() - datetime.timedelta(seconds = 10))
    
    def Authorize(self):
        assert self.refresh_token, "We don't have a refresh_token at all! How did that happen?"

        with self.authorization_lock:
            if self.needs_refresh:
                _URL_LOGIN = 'https://login.questrade.com/oauth2/token?grant_type=refresh_token&refresh_token='
                r = requests.get(_URL_LOGIN + self.refresh_token)
                r.raise_for_status()
                json = r.json()
                self.api_server = json['api_server'] + 'v1/'
                self.refresh_token = json['refresh_token']
                self.access_token = json['access_token']
                self.token_expiry = timezone.now() + datetime.timedelta(seconds = json['expires_in'])
                # Make sure to save out to DB
                self.save()

        self.session = requests.Session()
        self.session.headers.update({'Authorization': 'Bearer' + ' ' + self.access_token})

          
        
    def CloseSession(self):
        self.session.close()

    def _GetRequest(self, url, params={}):
        r = self.session.get(self.api_server + url, params=params)
        r.raise_for_status()
        return r.json()

    def SyncAccounts(self):
        json = self._GetRequest('accounts')
        for a in json['accounts']:
            Account.objects.update_or_create(type=json['type'], account_id=json['number'], client=self)
            
    def UpdateMarketPrices(self):
        symbols = Holding.current.filter(account__client=self, security__type=Security.Type.Stock).values_list('security__symbol', flat=True).distinct()
        securities = Security.stocks.filter(symbol__in=symbols)
        json = self._GetRequest('markets/quotes', 'ids=' + ','.join([str(s.symbolid) for s in securities if s.symbolid > 0]))
        for q in json['quotes']:
            price = q['lastTradePriceTrHrs']
            if not price: price = q['lastTradePrice']   
            if not price: 
                print('No price available for {}... zeroing out.', q['symbol'])
                price = 100
            stock = Security.stocks.get(symbol=q['symbol'])
            stock.livePrice = Decimal(str(price))
            stock.save()

        r = requests.get('https://openexchangerates.org/api/latest.json', params={'app_id':'eb324bcd04b743c2830360072d84e024', 'symbols':'CAD'})
        price = Decimal(str(r.json()['rates']['CAD']))
        Currency.objects.filter(code='USD').update(livePrice=price)
                            
    def _GetActivities(self, account_id, startTime, endTime):
        json = self._GetRequest('accounts/{}/activities'.format(account_id), {'startTime': startTime.isoformat(), 'endTime': endTime.isoformat()})
        logger.debug(json)
        return json['activities']

    def _FindSymbolId(self, symbol):
        json = self._GetRequest('symbols/search', {'prefix':symbol})
        for s in json['symbols']:
            if s['isTradable'] and symbol == s['symbol']: 
                logger.debug("Matching {} to {}".format(symbol, s))
                return s['symbolId']
        return 0

    def _GetSecurityInfoList(self, symbolids):
        if len(symbolids) == 0:
            return []
        if len(symbolids) == 1:
            json = self._GetRequest('symbols/{}'.format(','.join(map(str,symbolids))))
        else:     
            json = self._GetRequest('symbols', 'ids='+','.join(map(str,symbolids)))
        logger.debug(json)
        return json['symbols']
    
    def SyncActivities(self, startDate='2011-02-01'):
        for account in self.accounts.all():
            print ('Syncing all activities for {}: '.format(account), end='')
            start = account.GetMostRecentActivityDate()
            if start: start = arrow.get(start).shift(days=+1)
            else: start = arrow.get(startDate)
            
            date_range = arrow.Arrow.interval('day', start, arrow.now(), 30)
            print('{} requests'.format(len(date_range)), end='')
            for start, end in date_range:
                print('.',end='',flush=True)
                logger.debug(account.id, start, end)
                activities_list = self._GetActivities(account.id, start, end.replace(hour=0, minute=0, second=0))
                for json in activities_list: 
                    ActivityJson.Add(json, account)
            print()

    def UpdateSecurityInfo(self):
        with transaction.atomic():
            for stock in Security.stocks.all():
                if stock.symbolid == 0:
                    print('finding {}'.format(stock))
                    stock.symbolid = self._FindSymbolId(stock.symbol)
                    
                    print('finding {}'.format(stock.symbolid))
                    stock.save()

    def SyncCurrentAccountBalances(self):
        for a in self.accounts.all():
            json = self._GetRequest('accounts/%s/balances'%(a.id))           
            a.curBalanceSynced = next(currency['totalEquity'] for currency in json['combinedBalances'] if currency['currency'] == 'CAD')
            a.sodBalanceSynced = next(currency['totalEquity'] for currency in json['sodCombinedBalances'] if currency['currency'] == 'CAD')
            a.save()


def DoWork():
    DataProvider.Init()
    for a in Account.objects.all():
        a.RegenerateActivities()
        a.RegenerateHoldings()
    DataProvider.SyncAllSecurities()

def All():
    Currency.objects.all().delete()
    for c in Client.objects.all():
        c.Authorize()
        c.SyncActivities()
    DoWork()
