from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponse, Http404
from django.db.models.aggregates import Sum

from .models import BaseAccount, DataProvider, Holding, Security, SecurityPrice, Currency, BaseClient
from .models import GetValueDataFrame, GetHistoryValues
from .tasks import GetDailyUpdateTaskGroup, GetLiveUpdateTaskGroup
import arrow
import datetime
from collections import defaultdict
from decimal import Decimal
from questrade.utils import as_currency,  strdate
from contextlib import ExitStack
import plotly
import plotly.graph_objs as go

import pandas
import requests
from celery import group

def GetHoldingsContext():
    all_holdings = Holding.objects.current()
    total_gain = 0
    total_value = 0  

    security_data = []
    cash_data = []
        
    for symbol, qty in all_holdings.exclude(security__type=Security.Type.Cash).values_list('security__symbol').annotate(Sum('qty')):
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

    for symbol, qty in all_holdings.filter(security__type=Security.Type.Cash).values_list('security__symbol').annotate(Sum('qty')):
        cash_data.append((symbol.split()[0], qty))

    total = [(total_gain, total_gain / total_value, as_currency(total_value))]
    exchange_live = 1/Currency.objects.get(code='USD').live_price
    exchange_yesterday = 1/Currency.objects.get(code='USD').GetRateOnDay(datetime.date.today() - datetime.timedelta(days=1))
    exchange_delta = (exchange_live - exchange_yesterday) / exchange_yesterday
    context = {'security_data':security_data, 'total':total, 'cash_data':cash_data, 'exchange_live':exchange_live, 'exchange_delta':exchange_delta}
    return context

def GetBalanceContext():
    account_data = [(a.display_name, a.yesterday_balance, a.cur_balance, a.cur_cash_balance, a.cur_balance-a.yesterday_balance) for a in BaseAccount.objects.all() ]
    names,sod,cur,cur_cash,change = list(zip(*account_data))

    total_data = [('Total', sum(sod), sum(cur), sum(cur_cash), sum(change))]

    context = {'account_data':account_data, 'total_data':total_data }
    return context

def analyze(request):
    if not request.user.is_authenticated:
        raise Http404("No User!")
    plotly_html = '<iframe id="igraph" scrolling="no" style="border:none;" seamless="seamless" src="https://plot.ly/~cecilpl/2.embed?modebar=false&link=false" height="525" width="100%"/></iframe>'
    if request.is_ajax():        
        if 'refresh-live' in request.GET:
            result = GetLiveUpdateTaskGroup()()
            result.get()

        elif 'refresh-plot' in request.GET:
            pairs = GetHistoryValues()
            dates, vals = list(zip(*pairs))
            trace = go.Scatter(name='Total', x=dates, y=vals, mode='lines+markers')
            plotly_url = plotly.plotly.plot([trace], filename='portfolio-values-short', auto_open=False)
            plotly_html = plotly.tools.get_embed(plotly_url)

        elif 'refresh-account' in request.GET:
            for client in BaseClient.objects.all():
                with client:
                    client.Refresh()
            DataProvider.SyncAllSecurities()

    overall_context = {**GetHoldingsContext(), **GetBalanceContext()}
    overall_context['plotly_embed_html'] = plotly_html
    return render(request, 'finance/portfolio.html', overall_context)

def DoWorkHistory(request):
    df = GetValueDataFrame()
    traces = [go.Scatter(name=name, x=series.index, y=series.values) for name, series in df.iteritems()]    
    plotly_url = plotly.plotly.plot(traces, filename='portfolio-values', auto_open=False)
    plotly_embed_html=plotly.tools.get_embed(plotly_url)

    context = {
        'names': df.columns,
        'rows': df.itertuples(),
        'plotly_embed_html': plotly_embed_html
    }

    return render(request, 'finance/history.html', context)

def index(request):
    if request.user.is_authenticated:
        return render(request, 'finance/index.html')
    else:
        return redirect('/login/')
