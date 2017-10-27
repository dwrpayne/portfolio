from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse
from django.db.models.aggregates import Sum

# Create your views here.
from .models import Client, Account, DataProvider, Holding, Security, Currency
import arrow
import datetime
from .utils import as_currency,  strdate

def UpdatePrices():
    c=Client.objects.all()[0]
    c.Authorize()
    c.UpdateMarketPrices()   

def DoWork():
    yield "<html><body><pre>"
    
    all_holdings = Holding.current.all()

    yield '<br><br>Symbol\tPrice\t   Change\tShares\tGain (CAD)\tTotal Value (CAD)<br>'
    total_gain = 0
    total_value = 0  
    UpdatePrices()
        
    for symbol, qty in all_holdings.exclude(security__type=Security.Type.Cash).values_list('security__symbol').distinct().annotate(Sum('qty')):
        security = Security.objects.get(symbol=symbol)
        # TODO: Hacky to get it working.
        yesterday_price = security.GetLatestPrice()
        yesterday_price_CAD = security.GetLatestPrice() * security.currency.GetLatestRate()

        today_price = security.livePrice
        today_price_CAD = today_price * security.currency.livePrice

        price_delta = today_price - yesterday_price
        percent_delta = price_delta / yesterday_price
        this_gain = qty * (today_price_CAD - yesterday_price_CAD)
        total_gain += this_gain
        value_CAD = qty * today_price_CAD
        total_value += value_CAD
        color = "green" if price_delta > 0 else "red"
        yield '{0:} \t{1:.2f}\t<font color="{2:}">{3:+.2f} ({4:+.2%})</font>\t{5:.0f}  \t<font color="{2:}">{6:}</font>    \t{7:}<br>'.format(
            symbol.split('.')[0], today_price, color, price_delta, price_delta / yesterday_price, qty, as_currency(this_gain), as_currency(value_CAD))
    yield '-------------------------------------<br>'
    
    color = "green" if total_gain > 0 else "red"
    yield 'Total: \t\t<font color="{}">{:+,.2f} ({:+.2%})</font>\t\t\t{}<br>'.format(color, total_gain, total_gain / total_value, as_currency(total_value))
    yield '\nCurrent USD exchange: {:.4f}<br>'.format( 1/Currency.objects.get(code='USD').livePrice )
    yield '</pre></body></html>'
    
def analyze(request):
    return HttpResponse(DoWork()) 

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
    for day in arrow.Arrow.range('day', arrow.get(start), arrow.now()):
        d = day.date()
        account_vals = [int(value[d]) for value in value_lists]
        yield '<br>{}\t'.format(d) + '\t'.join([str(val) for val in account_vals]) + '\t' + str(sum(account_vals))
    yield '</pre></body></html>'

    
def history(request): 
    return HttpResponse(DoWorkHistory()) 

def AccountBalances(request):
    data = []
    for c in Client.objects.all():
        c.Authorize()
        for a in c.account_set.all():
            json = c._GetRequest('accounts/%s/balances'%(a.id))           
            cur_balance = next(currency['totalEquity'] for currency in json['combinedBalances'] if currency['currency'] == 'CAD')
            sod_balance = next(currency['totalEquity'] for currency in json['sodCombinedBalances'] if currency['currency'] == 'CAD')
            data.append(('{} {}'.format(c.username, a.type), sod_balance, cur_balance, cur_balance-sod_balance))
        c.CloseSession()

    names,sod,cur,change = list(zip(*data))
    data.append(('Total', sum(sod), sum(cur), sum(change)))

    context = {'data':data }
    return render(request, 'questrade/balances.html', context)

def index(request):
    return HttpResponse("Hello world, you're at the questrade index.")