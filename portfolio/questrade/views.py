from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse
from django.db.models.aggregates import Sum

from .models import Account, Client
from finance.models import BaseAccount, DataProvider, Holding, Security, Currency
import arrow
import datetime
from collections import defaultdict
from decimal import Decimal
from .utils import as_currency,  strdate
from contextlib import ExitStack
import plotly
import plotly.graph_objs as go
import requests

holding_refresh_count = 0
def GetHoldingsContext():
    global holding_refresh_count
    holding_refresh_count+=1
    all_holdings = Holding.current.all()
    total_gain = 0
    total_value = 0  

    security_data = []
        
    for symbol, qty in all_holdings.exclude(security__type=Security.Type.Cash).values_list('security__symbol').distinct().annotate(Sum('qty')):
        security = Security.objects.get(symbol=symbol)
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
        security_data.append((symbol.split('.')[0], today_price, price_delta, percent_delta, qty, this_gain, value_CAD))

    total = [(total_gain, total_gain / total_value, as_currency(total_value))]
    exchange = 1/Currency.objects.get(code='USD').livePrice
    context = {'security_data':security_data, 'total':total, 'exchange':exchange, 'holding_refresh_count':holding_refresh_count}
    return context

def analyze(request):
    if request.is_ajax():
        if 'refresh-holdings' in request.GET:
            with Client.objects.all()[0] as c:
                try:
                    c.UpdateMarketPrices()
                except requests.exceptions.HTTPError as e:
                    return HttpResponse(e.response.json(), content_type="application/json", status_code= e.response.status_code)

            return render(request, 'questrade/holdings.html', GetHoldingsContext())

        if 'refresh-balances' in request.GET:
            with ExitStack() as stack:
                clients = [stack.enter_context(c) for c in Client.objects.all()]
                try:
                    for c in clients:
                        c.SyncCurrentAccountBalances()                
                except requests.exceptions.HTTPError as e:
                    return HttpResponse(e.response.json(), content_type="application/json", status= e.response.status_code)
            return render(request, 'questrade/balances.html', GetBalanceContext())

    overall_context = {**GetHoldingsContext(), **GetBalanceContext()}
    return render(request, 'questrade/portfolio.html', overall_context)


balance_refresh_count = 0
def GetBalanceContext():
    global balance_refresh_count
    balance_refresh_count+=1
    account_data = [(a.display_name, a.sodBalanceSynced, a.curBalanceSynced, a.curBalanceSynced-a.sodBalanceSynced) for a in Account.objects.all() ]
    names,sod,cur,change = list(zip(*account_data))
    account_data.append(('Total', sum(sod), sum(cur), sum(change)))

    context = {'account_data':account_data, 'balance_refresh_count':balance_refresh_count }
    return context

def DoWorkHistory():
    yield "<html><body><pre>"
    yield "<br>"
    start = '2011-01-01'
    all_accounts = BaseAccount.objects.all()
    t = []    
    vals = defaultdict(Decimal)
    for a in all_accounts:
        pairs = a.GetValueList().items()
        x,y = list(zip(*pairs))
        t.append(go.Scatter(name=a.display_name, x=x, y=y))
        for date, v in a.GetValueList().items(): vals[date] += v

    total_x, total_y = list(zip(*sorted(vals.items())))
    trace = go.Scatter(name='Total', x=total_x, y=total_y)
    plotly.offline.plot(t+[trace])

    yield '<br>Date\t\t' + '\t'.join([name[0] + type for name, type in all_accounts.values_list('client__username', 'type')]) + '\tTotal'
    value_lists = [a.GetValueList() for a in all_accounts]
    for day in arrow.Arrow.range('day', arrow.get(start), arrow.now()):
        d = day.date()
        account_vals = [int(value[d]) for value in value_lists]
        yield '<br>{}\t'.format(d) + '\t'.join([str(val) for val in account_vals]) + '\t' + str(sum(account_vals))
    yield '</pre></body></html>'

    
def history(request): 
    return HttpResponse(DoWorkHistory()) 


def index(request):
    return HttpResponse("Hello world, you're at the questrade index.")
