from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse, StreamingHttpResponse

# Create your views here.
from .models import Client, Account, Holdings, Position, HackInitMyAccount, DataProvider
import arrow
import datetime
from utils import as_currency,  strdate


def SyncNewData(start):
    for client in Client.objects.all():
        c.Authorize()
        c.SyncAccounts()
        c.SyncAllActivitiesSlow(start)
        c.SyncPrices(start)
        c.UpdateMarketPrices()

def GetFullClientData(client_name):
    c = Client.objects.get(username=client_name)
    print('{}: Authorizing'.format(client_name))
    c.Authorize()
    for a in c.GetAccounts(): 
        HackInitMyAccount(a)    
        print('{}: Processing {}'.format(client_name, a))
        a.ProcessActivityHistory()
    print('{}: Updating market prices'.format(client_name))
    c.UpdateMarketPrices()    
    c.CloseSession()
    return c

def GetProcessedAccounts(client_name):    
    return GetFullClientData(client_name).GetAccounts()

def GetAllPositions(client_name):
    return GetFullClientData(client_name).GetPositions()

def DoWork():
    yield "<html><body><pre>"
    yield "<br>Syncing Data..."

    data_provider = DataProvider('CAD')
    data_provider.SyncExchangeRates('USD')
    
    yield "<br>Processing accounts..."
    positions = []
    try:
        positions = GetAllPositions('David') + GetAllPositions('Sarah')
    except Exception as e:
        yield "<br>Error processing, please try again later."
        return

    yield '<br><br>Symbol\tPrice\t\t   Change\t\tShares\tGain<br>'
    total_gain = 0
    total_value = 0
    for symbol in ['VBR', 'VTI', 'VUN.TO', 'VXUS', 'VCN.TO', 'VAB.TO', 'VDU.TO', 'TSLA']:
        total_pos = sum([p for p in positions if p.symbol==symbol])
        yesterday_price = data_provider.GetPrice(symbol, datetime.date.today() - datetime.timedelta(days=1))
        price_delta = total_pos.marketprice-yesterday_price
        this_gain = price_delta * total_pos.qty * data_provider.GetExchangeRate(total_pos.currency, datetime.date.today())
        total_gain += this_gain
        total_value += total_pos.GetMarketValueCAD()
        color = "green" if price_delta > 0 else "red"
        yield '{} \t{:.2f}\t\t<font color="{}">{:+.2f} ({:+.2%})</font>\t\t{:.0f}  \t{}<br>'.format(
            symbol.split('.')[0], total_pos.marketprice, color, price_delta, price_delta / yesterday_price, total_pos.qty, as_currency(this_gain))
    yield '-------------------------------------<br>'
    
    color = "green" if total_gain > 0 else "red"
    yield 'Total: \t\t\t<font color="{}">{:+,.2f}({:+.2%})</font>\t{}<br>'.format(color, total_gain, total_gain / total_value, as_currency(total_value))
    yield '\nCurrent USD exchange: {:.4f}<br>'.format( 1/data_provider.GetExchangeRate('USD', datetime.date.today()))
    yield '</pre></body></html>'
    
def analyze(request):
    return StreamingHttpResponse(DoWork())

def DoWorkHistory():
    yield "<html><body><pre>"
    yield "<br>Syncing Data..."

    data_provider = DataProvider('CAD')
    data_provider.SyncExchangeRates('USD')
    
    yield "<br>Processing David's accounts..."    
    all_accounts = GetProcessedAccounts('David')
    yield "<br>Processing Sarah's accounts..." 
    all_accounts += GetProcessedAccounts('Sarah')
    yield "<br>Processing history"
    for a in all_accounts:
        a.GenerateHoldingsHistory()
        yield "."
    yield "<br>"

    start = min([min(a.GetAllHoldings()) for a in all_accounts])
    yield '<br>Date\t\t' + '\t'.join([a.client.username[0] + a.type for a in all_accounts]) + '\tTotal'
    for day in arrow.Arrow.range('day', arrow.get(start), arrow.now()):
        d = strdate(day)
        account_vals = [int(a.GetHistoricalValueAtDate(d)) for a in all_accounts]
        yield '<br>' + d + '\t' + '\t'.join([str(val) for val in account_vals]) + '\t' + str(sum(account_vals))
    yield '</pre></body></html>'

def history(request):
    return StreamingHttpResponse(DoWorkHistory())  

def DoWorkHistoryNew():
    yield "<html><body><pre>"
    yield "<br>Syncing Data..."
    yield "<br>Processing history"
    all_accounts = Account.objects.all()[:1]
    #for a in all_accounts:
    #    a.RegenerateDBHoldings()
    #    yield "."
    yield "<br>"
    start = '2011-01-01'
    yield '<br>Date\t\t' + '\t'.join([a.client.username[0] + a.type for a in all_accounts]) + '\tTotal'
    for day in arrow.Arrow.range('day', arrow.get(start), arrow.now()):
        d = day.date()
        account_vals = [int(a.GetValueAtDate(d)) for a in all_accounts]
        yield '<br>{}\t'.format(d) + '\t'.join([str(val) for val in account_vals]) + '\t' + str(sum(account_vals))
    yield '</pre></body></html>'

def historynew(request):
    return StreamingHttpResponse(DoWorkHistoryNew())  

def AccountBalances():
    yield "<html><body><pre>"
    yield "<br>Syncing Data..."
    yield "<br>Account\tSOD in CAD\tCurrent CAD"
    for c in Client.objects.all():
        c.Authorize()
        for a in c.GetAccounts():
            json = c._GetRequest('accounts/%s/balances'%(a.account_id))            
            combinedCAD = next(currency['totalEquity'] for currency in json['combinedBalances'] if currency['currency'] == 'CAD')
            sodCombinedCAD = next(currency['totalEquity'] for currency in json['sodCombinedBalances'] if currency['currency'] == 'CAD')
            yield "<br>{} {}\t{}\t{}".format(a.client.username, a.type, sodCombinedCAD, combinedCAD)

def balances(request):    
    return StreamingHttpResponse(AccountBalances())  

def index(request):
    return HttpResponse("Hello world, you're at the questrade index.")