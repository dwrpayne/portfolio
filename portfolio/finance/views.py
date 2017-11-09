from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponse, Http404
from django.db.models.aggregates import Sum
from django.db.models import F, Q, Sum
from django.contrib.auth.decorators import login_required

from .models import BaseAccount, DataProvider, Holding, Security, SecurityPrice, Currency
from .tasks import GetLiveUpdateTaskGroup
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


def GetHistoryValues(user, startdate=None):
    """ Returns an (date, value) tuple for each date where the value of that account is > 0 """
    pricequery = SecurityPrice.objects.filter(security__holdings__account__client__user=user)
    if startdate: 
        pricequery = SecurityPrice.objects.filter(day__gte=startdate)
    
    val_list = pricequery.filter(
        Q(security__holdings__enddate__gte=F('day'))|Q(security__holdings__enddate=None), 
        security__holdings__startdate__lte=F('day'),
        security__currency__rates__day=F('day')
    ).order_by('day').values_list('day').annotate( val=Sum(F('price') * F('security__holdings__qty') * F('security__currency__rates__price')) )
    
    return val_list

def GetValueDataFrame(startdate=None):
    """ Returns an (account, date, value) tuple for each date where the value of that account is > 0 """
    pricequery = SecurityPrice.objects.filter(security__holdings__account__client__user=user)
    if startdate: 
        pricequery = SecurityPrice.objects.filter(day__gte=startdate)
    
    val_list = pricequery.filter(
        Q(security__holdings__enddate__gte=F('day'))|Q(security__holdings__enddate=None), 
        security__holdings__startdate__lte=F('day'),
        security__currency__rates__day=F('day')
    ).values_list('day', 'security__holdings__account_id').annotate(
        val=Sum(F('price') * F('security__holdings__qty') * F('security__currency__rates__price'))
    )

    all_accounts = BaseAccount.objects.all()
    dates = sorted(list({d for d,a,v in val_list}))

    vals = defaultdict(dict)
    for d,a,v in val_list:
        vals[a][pandas.Timestamp(d)] = v
    
    s = [pandas.Series(vals[a.id], name=a.display_name) for a in all_accounts]
    df = pandas.DataFrame(s).T.fillna(0).astype(int).iloc[::-1]
    df = df.assign(Total=pandas.Series(df.sum(1)))
    df.index = df.index.date
    return df


def GetHoldingsContext(user):
    all_holdings = Holding.objects.filter(account__client__user=user).current()
    if not all_holdings.exists():
        return {}
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

        security_data.append([symbol.split('.')[0], today_price, price_delta, percent_delta, qty, this_gain, value_CAD])

    for d in security_data:
        d.append(d[6] / total_value * 100)        

    for symbol, qty in all_holdings.filter(security__type=Security.Type.Cash).values_list('security__symbol').annotate(Sum('qty')):
        cash_data.append((symbol.split()[0], qty))

    total = [(total_gain, total_gain / total_value, as_currency(total_value))]
    exchange_live = 1/Currency.objects.get(code='USD').live_price
    exchange_yesterday = 1/Currency.objects.get(code='USD').GetRateOnDay(datetime.date.today() - datetime.timedelta(days=1))
    exchange_delta = (exchange_live - exchange_yesterday) / exchange_yesterday
    context = {'security_data':security_data, 'total':total, 'cash_data':cash_data, 'exchange_live':exchange_live, 'exchange_delta':exchange_delta}
    return context

def GetBalanceContext(user):
    accounts = BaseAccount.objects.filter(client__user=user)
    if not accounts.exists():
        return {}
    account_data = [(a.display_name, a.yesterday_balance, a.cur_balance, a.cur_cash_balance, a.cur_balance-a.yesterday_balance) for a in accounts ]

    names,sod,cur,cur_cash,change = list(zip(*account_data))

    total_data = [('Total', sum(sod), sum(cur), sum(cur_cash), sum(change))]

    context = {'account_data':account_data, 'total_data':total_data }
    return context

@login_required
def analyze(request):
    plotly_html = '<iframe id="igraph" scrolling="no" style="border:none;" seamless="seamless" src="https://plot.ly/~cecilpl/2.embed?modebar=false&link=false" height="525" width="100%"/></iframe>'
    if request.is_ajax():        
        if 'refresh-live' in request.GET:
            result = GetLiveUpdateTaskGroup(request.user)()
            result.get()

        elif 'refresh-plot' in request.GET:
            pairs = GetHistoryValues(request.user, datetime.date.today() - datetime.timedelta(days=30))
            dates, vals = list(zip(*pairs))
            trace = go.Scatter(name='Total', x=dates, y=vals, mode='lines+markers')
            plotly_url = plotly.plotly.plot([trace], filename='portfolio-values-short', auto_open=False)
            plotly_html = plotly.tools.get_embed(plotly_url)

        elif 'refresh-account' in request.GET:
            for client in request.user.clients.all():
                with client:
                    client.Refresh()
            DataProvider.SyncAllSecurities()

    overall_context = {**GetHoldingsContext(request.user), **GetBalanceContext(request.user)}
    overall_context['plotly_embed_html'] = plotly_html
    return render(request, 'finance/portfolio.html', overall_context)

@login_required
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
