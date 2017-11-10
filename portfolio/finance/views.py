from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponse, Http404
from django.db.models.aggregates import Sum
from django.db.models import F, Q, Sum, When, Case, Max
from django.contrib.auth.decorators import login_required

from .models import BaseAccount, DataProvider, Holding, Security, SecurityPrice, Currency
from .tasks import GetLiveUpdateTaskGroup
import arrow
import datetime
from collections import defaultdict
from decimal import Decimal
from contextlib import ExitStack
import plotly
import plotly.graph_objs as go

import pandas
import requests
from celery import group


def GetHistoryValues(user, startdate=None):
    query = SecurityPrice.objects.all()
    if startdate:
        query = query.filter(day__gte=startdate)

    return query.filter(
        Q(security__holdings__enddate__gte=F('day'))|Q(security__holdings__enddate=None), 
        security__holdings__account__client__user=user, 
        security__holdings__startdate__lte=F('day'),
        security__currency__rates__day=F('day')).values('day').order_by('day').annotate(
            val=Sum(F('price')*F('security__holdings__qty') * F('security__currency__rates__price'))
            ).values_list()

def GetValueDataFrame(user, startdate=None):
    """ Returns an (account, date, value) tuple for each date where the value of that account is > 0 """
    pricequery = SecurityPrice.objects.all()
    if startdate: 
        pricequery = SecurityPrice.objects.filter(day__gte=startdate)
    
    val_list = pricequery.filter(
        Q(security__holdings__enddate__gte=F('day'))|Q(security__holdings__enddate=None), 
        security__holdings__account__client__user=user, 
        security__holdings__startdate__lte=F('day'),
        security__currency__rates__day=F('day')
    ).values('day', 'security__holdings__account_id').annotate(
        val=Sum(F('price') * F('security__holdings__qty') * F('security__currency__rates__price'))
    ).values_list('day', 'security__holdings__account_id', 'val')

    dates = val_list.dates('day', 'day')

    vals = defaultdict(dict)
    for d,a,v in val_list:
        vals[a][pandas.Timestamp(d)] = v
    
    s = [pandas.Series(vals[a.id], name=a.display_name) for a in BaseAccount.objects.filter(client__user=user)]
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

        security_data.append([symbol, today_price, price_delta, percent_delta, qty, this_gain, value_CAD])

    for d in security_data:
        d.append(d[6] / total_value * 100)

    for symbol, qty in all_holdings.filter(security__type=Security.Type.Cash).values_list('security__symbol').annotate(Sum('qty')):
        cash_data.append((symbol.split()[0], qty))

    total = [(total_gain, total_gain / total_value, total_value)]
    exchange_live = 1/Currency.objects.get(code='USD').live_price
    exchange_yesterday = 1/Currency.objects.get(code='USD').GetRateOnDay(datetime.date.today() - datetime.timedelta(days=1))
    exchange_delta = (exchange_live - exchange_yesterday) / exchange_yesterday
    context = {'security_data':security_data, 'total':total, 'cash_data':cash_data, 'exchange_live':exchange_live, 'exchange_delta':exchange_delta}
    return context

def GetBalanceContext(user):
    accounts = BaseAccount.objects.filter(client__user=user)
    if not accounts.exists():
        return {}
   
    account_data = [(a.display_name, a.id, a.yesterday_balance, a.cur_balance, a.cur_cash_balance, a.cur_balance-a.yesterday_balance) for a in accounts ]

    names,ids, sod,cur,cur_cash,change = list(zip(*account_data))

    total_data = [('Total', sum(sod), sum(cur), sum(cur_cash), sum(change))]

    context = {'account_data':account_data, 'total_data':total_data }
    return context

def GeneratePlot(user):
    pairs = GetHistoryValues(user, datetime.date.today() - datetime.timedelta(days=30))
    dates, vals = list(zip(*pairs))
    trace = go.Scatter(name='Total', x=dates, y=vals, mode='lines+markers')
    plotly_url = plotly.plotly.plot([trace], filename='portfolio-values-short-{}'.format(user.username), auto_open=False)
    user.userprofile.plotly_url = plotly_url    
    user.userprofile.save()

@login_required
def analyze(request):
    if not request.user.userprofile.plotly_url:
        GeneratePlot(request.user)

    plotly_html = '<iframe id="igraph" scrolling="no" style="border:none;" seamless="seamless" src="{}?modebar=false&link=false" height="525" width="100%"/></iframe>'.format(request.user.userprofile.plotly_url)
    if request.is_ajax():        
        if 'refresh-live' in request.GET:
            result = GetLiveUpdateTaskGroup(request.user)()
            result.get()

        elif 'refresh-plot' in request.GET:
            GeneratePlot(request.user)
            plotly_html = plotly.tools.get_embed(request.user.userprofile.plotly_url)

        elif 'refresh-account' in request.GET:
            for client in request.user.clients.all():
                with client:
                    client.Refresh()
            DataProvider.SyncAllSecurities()

    overall_context = {**GetHoldingsContext(request.user), **GetBalanceContext(request.user)}
    overall_context['plotly_embed_html'] = plotly_html
    overall_context['username'] = request.user.username
    return render(request, 'finance/portfolio.html', overall_context)

@login_required
def DoWorkHistory(request):
    data = GetHistoryValuesByAccount(request.user)

    df = GetValueDataFrame(request.user)
    traces = [go.Scatter(name=name, x=series.index, y=series.values) for name, series in df.iteritems()]    
    plotly_url = plotly.plotly.plot(traces, filename='portfolio-values', auto_open=False)
    plotly_embed_html=plotly.tools.get_embed(plotly_url)

    context = {
        'names': df.columns,
        'rows': df.itertuples(),
        'plotly_embed_html': plotly_embed_html
    }

    return render(request, 'finance/history.html', context)

@login_required
def accountdetail(request, account_id):
    account = BaseAccount.objects.get(id=account_id)
    if not account.client.user == request.user:
        return HttpResponse('Unauthorized', status=401)

    activities = list(account.activities.all())

    context = {'account':account, 'activities':activities}
    return render(request, 'finance/account.html', context)    


import simplejson
from .models import Activity

@login_required
def securitydetail(request, symbol):
    activities = Security.objects.get(symbol=symbol).activities.filter(
        account__client__user=request.user, account__taxable=True, security__currency__rates__day=F('tradeDate')
        ).exclude(type='Dividend').order_by('tradeDate').annotate(exch=Sum(F('security__currency__rates__price')))

    totalqty = Decimal('0')
    totalacb = Decimal('0')
    activities = list(activities)
    for act in activities:

        act.cadprice = act.exch * act.price
        if not act.cadprice: act.cadprice = act.security.GetPriceCAD(act.tradeDate)
        act.commission = abs(act.exch * Decimal(simplejson.loads(act.raw.jsonstr)['commission']))

        prevacbpershare = totalacb / totalqty if totalqty else 0

        act.capgain = 0
        if act.qty < 0:
            act.capgain = (act.cadprice * abs(act.qty)) - act.commission - ((prevacbpershare) * abs(act.qty))

        if act.qty > 0:
            act.acbchange = act.cadprice * act.qty + act.commission
        else:
            act.acbchange = -(prevacbpershare) * abs(act.qty)

                                
        for security, amt in act.GetHoldingEffect().items():
            if security.symbol==symbol:
                totalqty += amt
        
        act.totalqty = totalqty     

        totalacb += act.acbchange
        totalacb = max(0, totalacb)
        act.totalacb = totalacb
        act.acbpershare = act.totalacb / act.totalqty if totalqty else 0
          


    context = {'activities':activities, 'symbol':symbol}
    return render(request, 'finance/security.html', context)    


def index(request):
    if request.user.is_authenticated:
        return render(request, 'finance/index.html')
    else:
        return redirect('/login/')
