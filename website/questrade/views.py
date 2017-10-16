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
    for a in c.GetAccounts(): 
        HackInitMyAccount(a)
        if len(a.GetPositions()) > 0: 
            a.holdings[start] = Holdings(arrow.get(start), a.GetPositions(), a.currentHoldings.cashByCurrency)
    
    c.SyncAllActivitiesSlow(start)
    c.SyncPrices(start)
    #c.GenerateHoldingsHistory()
    c.UpdateMarketPrices()
    return c

def DoWork():
    start = '2011-02-01'
    data_provider = DataProvider('CAD')
    data_provider.SyncExchangeRates('USD')

    david = GetFullClientData('David', start)
    sarah = GetFullClientData('Sarah', start)
    
    positions = david.GetPositions() + sarah.GetPositions()

    

    yield '\nSymbol\tPrice\t\t   Change\t\tShares\tGain'
    total_gain = 0
    total_value = 0
    for symbol in ['VBR', 'VTI', 'VUN.TO', 'VXUS', 'VCN.TO', 'VAB.TO', 'VDU.TO', 'TSLA']:
        total_pos = sum([p for p in positions if p.symbol==symbol])
        yesterday_price = data_provider.GetPrice(symbol, datetime.date.today() - datetime.timedelta(days=1))
        price_delta = total_pos.marketprice-yesterday_price
        this_gain = price_delta * total_pos.qty * data_provider.GetExchangeRate(total_pos.currency, datetime.date.today())
        total_gain += this_gain
        total_value += total_pos.GetMarketValueCAD()
        yield "{} \t{:.2f}\t\t{:+.2f} ({:+.2%})\t\t{}  \t{}".format(symbol.split('.')[0], total_pos.marketprice, price_delta, price_delta / yesterday_price, total_pos.qty, as_currency(this_gain))
    yield '-------------------------------------'
    yield 'Total: \t\t\t{:+,.2f}({:+.2%})\t{}'.format(total_gain, total_gain / total_value, as_currency(total_value))
    yield '\nCurrent USD exchange: {:.4f}'.format( 1/data_provider.GetExchangeRate('USD', datetime.date.today()))

    david.CloseSession()
    sarah.CloseSession()

def analyze(request):
    def Fixup(response):
        yield '<html><body><pre>'
        for line in response:
            line += '<br>'
            if '+' in line: 
                yield '<font color="green">{}</font>'.format(line)
            elif '-' in line: 
                yield '<font color="red">{}</font>'.format(line)
            else: 
                yield line
        return '</pre></body></html>'

    return StreamingHttpResponse(Fixup(DoWork()))

def index(request):
    return HttpResponse("Hello world, you're at the questrade index.")