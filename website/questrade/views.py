from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse, StreamingHttpResponse

# Create your views here.
from .models import Client, Account, Holdings, Position, HackInitMyAccount, DataProvider
import arrow
import datetime
from utils import as_currency,  strdate

def GetFullClientData(client_name, start):
    c = Client.objects.get(username=client_name)
    c.Authorize()
    #c.SyncAllActivitiesSlow(start)
    for a in c.GetAccounts(): 
        HackInitMyAccount(a)
        if len(a.GetPositions()) > 0: 
            a.holdings[start] = Holdings(arrow.get(start), a.GetPositions(), a.currentHoldings.cashByCurrency)
    
        a.ProcessActivityHistory()
    #c.SyncPrices(start)
    #c.GenerateHoldingsHistory()
    c.UpdateMarketPrices()
    return c

def DoWork():
    yield "<html><body><pre>"
    start = '2011-02-01'
    data_provider = DataProvider('CAD')
    yield "<br>Syncing Data...<br>"
    data_provider.SyncExchangeRates('USD')

    david = GetFullClientData('David', start)
    sarah = GetFullClientData('Sarah', start)
    
    positions = david.GetPositions() + sarah.GetPositions()
    
    yield 'Symbol\tPrice\t\t   Change\t\tShares\tGain<br>'
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
        yield '{} \t{:.2f}\t\t<font color="{}">{:+.2f} ({:+.2%})</font>\t\t{}  \t{}<br>'.format(
            symbol.split('.')[0], total_pos.marketprice, color, price_delta, price_delta / yesterday_price, total_pos.qty, as_currency(this_gain))
    yield '-------------------------------------<br>'
    
    color = "green" if total_gain > 0 else "red"
    yield 'Total: \t\t\t<font color="{}">{:+,.2f}({:+.2%})</font>\t{}<br>'.format(color, total_gain, total_gain / total_value, as_currency(total_value))
    yield '\nCurrent USD exchange: {:.4f}<br>'.format( 1/data_provider.GetExchangeRate('USD', datetime.date.today()))

    david.CloseSession()
    sarah.CloseSession()
    yield '</pre></body></html>'

def analyze(request):
    return StreamingHttpResponse(DoWork())

def index(request):
    return HttpResponse("Hello world, you're at the questrade index.")