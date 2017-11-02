from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse
from django.db.models.aggregates import Sum

from .models import QuestradeAccount, QuestradeClient
from finance.models import BaseAccount, DataProvider, Holding, Security, SecurityPrice, Currency, BaseClient
from finance.tasks import SyncClientPrices, SyncClientAccountBalances
import arrow
import datetime
from collections import defaultdict
from decimal import Decimal
from .utils import as_currency,  strdate
from contextlib import ExitStack
import plotly
import plotly.graph_objs as go
import requests
from celery import group

                 
def GetAccountValueList():
    val_list = SecurityPrice.objects.filter(
        Q(security__holdings__enddate__gte=F('day'))|Q(security__holdings__enddate=None), 
        security__holdings__startdate__lte=F('day'),
        security__currency__rates__day=F('day')
    ).values_list('security__holdings__account_id', 'day').annotate(
        val=Sum(F('price') * F('security__holdings__qty') * F('security__currency__rates__price'))
    )
    d = defaultdict(int)
    d.update({date:val for date,val in val_list})
    return d  
        

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
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        yesterday_price = security.GetPrice(yesterday)
        yesterday_price_CAD = security.GetPriceCAD(yesterday)

        today_price = security.live_price
        today_price_CAD = today_price * security.currency.live_price

        price_delta = today_price - yesterday_price
        percent_delta = price_delta / yesterday_price
        this_gain = qty * (today_price_CAD - yesterday_price_CAD)
        total_gain += this_gain
        value_CAD = qty * today_price_CAD
        total_value += value_CAD
        security_data.append((symbol.split('.')[0], today_price, price_delta, percent_delta, qty, this_gain, value_CAD))

    total = [(total_gain, total_gain / total_value, as_currency(total_value))]
    exchange_live = 1/Currency.objects.get(code='USD').live_price
    exchange_yesterday = 1/Currency.objects.get(code='USD').GetRateOnDay(datetime.date.today() - datetime.timedelta(days=1))
    exchange_delta = (exchange_live - exchange_yesterday) / exchange_yesterday
    context = {'security_data':security_data, 'total':total, 'exchange_live':exchange_live, 'exchange_delta':exchange_delta, 'holding_refresh_count':holding_refresh_count}
    return context

def analyze(request):
    if request.is_ajax():
        if 'refresh-holdings' in request.GET:
            job = group([SyncClientPrices.s(c.pk) for c in QuestradeClient.objects.all()])
            result = job.apply_async()
            result.join()
            DataProvider.UpdateLatestExchangeRates()
            return render(request, 'questrade/holdings.html', GetHoldingsContext())    

        if 'refresh-balances' in request.GET:
            job = group([SyncClientAccountBalances.s(c.pk) for c in QuestradeClient.objects.all()])
            result = job.apply_async()
            result.join()
            return render(request, 'questrade/balances.html', GetBalanceContext())

    overall_context = {**GetHoldingsContext(), **GetBalanceContext()}
    return render(request, 'questrade/portfolio.html', overall_context)


balance_refresh_count = 0
def GetBalanceContext():
    global balance_refresh_count
    balance_refresh_count+=1
    account_data = [(a.display_name, a.yesterday_balance, a.cur_balance, a.cur_balance-a.yesterday_balance) for a in BaseAccount.objects.all() ]
    names,sod,cur,change = list(zip(*account_data))
    account_data.append(('Total', sum(sod), sum(cur), sum(change)))

    context = {'account_data':account_data, 'balance_refresh_count':balance_refresh_count }
    return context

def DoWorkHistory():
    yield "<html><body><pre>"
    yield "<br>"
    start = '2009-06-01'
    all_accounts = BaseAccount.objects.all()
    t = []    
    vals = defaultdict(Decimal)
    data = GetAccountValueList()
    for a in all_accounts:
        
        pairs = data.filter(account_id=a.id).items()
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
