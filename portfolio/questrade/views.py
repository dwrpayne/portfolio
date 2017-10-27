from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse, StreamingHttpResponse
from django.db.models.aggregates import Sum

# Create your views here.
from .models import Client, Account, DataProvider, Holding, SecurityPrice
import arrow
import datetime
from .utils import as_currency,  strdate

def UpdatePrices():
    for client in Client.objects.all():
        client.Authorize()
        client.SyncPrices('2017-10-10')
        client.UpdateMarketPrices()   


def DoWork():
    yield "<html><body><pre>"
    yield "<br>Syncing Data..."
    
    all_holdings = Holding.current.all()

    yield '<br><br>Symbol\tPrice\t\t   Change\t\tShares\tGain<br>'
    total_gain = 0
    total_value = 0  
    UpdatePrices()
        
    for symbol, qty in all_holdings.values_list('symbol').distinct().annotate(Sum('qty')):
        total_qty = sum(all_holdings.filter(symbol=symbol).values_list('qty', flat=True))

        # TODO: Hacky to get it working.
        yesterday_price = DataProvider.GetPrice(symbol, datetime.date.today() - datetime.timedelta(days=1))
        today_price = DataProvider.GetPrice(symbol, datetime.date.today())
        price_delta = today_price - yesterday_price
        this_gain = price_delta * total_qty * DataProvider.GetExchangeRate('CAD' if '.TO' in symbol else 'USD', datetime.date.today())
        total_gain += this_gain
        total_value += total_qty * today_price * DataProvider.GetExchangeRate('CAD' if '.TO' in symbol else 'USD', datetime.date.today())
        color = "green" if price_delta > 0 else "red"
        yield '{} \t{:.2f}\t\t<font color="{}">{:+.2f} ({:+.2%})</font>\t\t{:.0f}  \t{}<br>'.format(
            symbol.split('.')[0], today_price, color, price_delta, price_delta / yesterday_price, total_qty, as_currency(this_gain))
    yield '-------------------------------------<br>'
    
    color = "green" if total_gain > 0 else "red"
    yield 'Total: \t\t\t<font color="{}">{:+,.2f}({:+.2%})</font>\t{}<br>'.format(color, total_gain, total_gain / total_value, as_currency(total_value))
    yield '\nCurrent USD exchange: {:.4f}<br>'.format( 1/DataProvider.GetExchangeRate('USD', datetime.date.today()))
    yield '</pre></body></html>'
    
def analyze(request):
    return HttpResponse(DoWork()) 
    return StreamingHttpResponse(DoWork())

# WOAH
#for acc in a:
#  x,y = list(zip(*acc.GetValueList().items()))
#  t.append(go.Scatter(name=acc.client.username + ' ' +acc.type, x=x, y=y))

#vals = defaultdict(Decimal)
#for acc in a:
#       for date, v in acc.GetValueList().items(): vals[date] += v
#pair = list(zip(*sorted(vals.items())))
#trace = go.Scatter(name='Total', x=pair[0], y=pair[1])
#plotly.offline.plot(t+[trace])



def DoWorkHistory():
    yield "<html><body><pre>"
    yield "<br>Syncing Data..."
    yield "<br>Processing history"
    all_accounts = Account.objects.all()
    yield "<br>"
    start = '2011-01-01'
    yield '<br>Date\t\t' + '\t'.join([name[0] + type for name, type in all_accounts.values_list('client__username', 'type')]) + '\tTotal'
    value_lists = [a.GetValueList() for a in all_accounts]
    for day in arrow.Arrow.range('day', arrow.get(start), arrow.now().shift(days=-4)):
        d = day.date()
        account_vals = [int(value[d]) for value in value_lists]
        yield '<br>{}\t'.format(d) + '\t'.join([str(val) for val in account_vals]) + '\t' + str(sum(account_vals))
    yield '</pre></body></html>'

    
def history(request): 
    return HttpResponse(DoWorkHistory()) 

def AccountBalances():
    yield "<html><body><pre>"
    yield "<br>Syncing Data..."
    yield "<br>Account\t\tSOD in CAD\tCurrent CAD\tChange"
    total_sod = 0
    total_current = 0
    for c in Client.objects.all():
        c.Authorize()
        for a in c.account_set.all():
            json = c._GetRequest('accounts/%s/balances'%(a.id))            
            combinedCAD = next(currency['totalEquity'] for currency in json['combinedBalances'] if currency['currency'] == 'CAD')
            sodCombinedCAD = next(currency['totalEquity'] for currency in json['sodCombinedBalances'] if currency['currency'] == 'CAD')
            total_current += combinedCAD
            total_sod += sodCombinedCAD

            price_delta = combinedCAD - sodCombinedCAD
            color = "green" if price_delta > 0 else "red"
            yield "<br>{} {}\t{}\t{}\t<font color=\"{}\">{}</font>".format(
                a.client.username, a.type, as_currency(sodCombinedCAD), as_currency(combinedCAD), color, as_currency(price_delta)
                )

        
    price_delta = total_current - total_sod
    color = "green" if price_delta > 0 else "red"
    yield "<br><br>Total\t\t{}\t{}\t<font color=\"{}\">{}</font>".format(
            as_currency(total_current), as_currency(total_sod), color, as_currency(price_delta)
            )

def balances(request):    
    return HttpResponse(AccountBalances())  

def index(request):
    return HttpResponse("Hello world, you're at the questrade index.")