from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponse, Http404
from django.db.models.aggregates import Sum
from django.db.models import F, Q, Sum, When, Case, Max, Value
from django.contrib.auth.decorators import login_required

from .models import BaseAccount, DataProvider, Holding, Security, SecurityPrice, Currency
from .tasks import GetLiveUpdateTaskGroup, DailyUpdateTask
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
import itertools


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
            ).values_list('day', 'val')

def GetHistoryValuesByAccount(user, startdate=None):
    query = SecurityPrice.objects.all()
    if startdate:
        query = query.filter(day__gte=startdate)
                
    return query.filter(
        Q(security__holdings__enddate__gte=F('day'))|Q(security__holdings__enddate=None), 
        security__holdings__account__client__user=user, 
        security__holdings__startdate__lte=F('day'),
        security__currency__rates__day=F('day')).values('day', 'security__holdings__account').order_by().annotate(
            val=Sum(F('price')*F('security__holdings__qty') * F('security__currency__rates__price'))
            ).values_list('day', 'security__holdings__account', 'val')

def GetValueDataFrame(user, startdate=None):
    """ Returns an (account, date, value) tuple for each date where the value of that account is > 0 """
    val_list = GetHistoryValuesByAccount(user, startdate)

    dates = val_list.dates('day', 'day')

    vals = defaultdict(dict)
    for d,a,v in val_list:
        vals[a][pandas.Timestamp(d)] = v
    
    s = [pandas.Series(vals[a.id], name=a.display_name) for a in BaseAccount.objects.filter(client__user=user)]
    df = pandas.DataFrame(s).T.fillna(0).astype(int).iloc[::-1]
    df = df.assign(Total=pandas.Series(df.sum(1)))
    df.index = df.index.date
    return df

class HoldingView:
    def __init__(self, yesterday, today):
        assert yesterday.symbol == today.symbol
        self.symbol = today.symbol
        self.qty = today.qty
        yesterday_price = yesterday.price
        yesterday_price_CAD = yesterday.price * yesterday.exch
        self.today_price = today.price
        today_price_CAD = today.price * today.exch
        self.price_delta = self.today_price - yesterday_price
        self.percent_delta = self.price_delta / yesterday_price
        self.this_gain = self.qty * (today_price_CAD - yesterday_price_CAD)
        self.value_CAD = self.qty * today_price_CAD

        if hasattr(today, 'acc'):
            self.acc = today.acc

def GetHoldingViewList(user, by_account=False):
    data = Security.objects.with_prices(user, datetime.date.today() - datetime.timedelta(days=1), by_account)
    return list(map(HoldingView, data[::2], data[1::2]))

def GetHoldingsContext(user):    
    total_value = Holding.objects.current().owned_by(user).value_as_of(datetime.date.today())
    total_yesterday = Holding.objects.current().owned_by(user).value_as_of(datetime.date.today() - datetime.timedelta(days=1))
    total_gain = total_value - total_yesterday
    
    holding_data = GetHoldingViewList(user)    
    account_data = GetHoldingViewList(user, True)    
    for view in holding_data:
        view.percent = view.value_CAD / total_value * 100
        view.account_data = [d for d in account_data if d.symbol == view.symbol]
        for account_view in view.account_data:
            account_view.percent = account_view.value_CAD / total_value * 100

    holding_data.sort(key=lambda h:h.value_CAD, reverse=True)
            
    total = [(total_gain, total_gain / total_value, total_value)]
    context = {'security_data':holding_data, 'total':total}
    return context

def GetBalanceContext(user):
    accounts = BaseAccount.objects.filter(client__user=user)
    if not accounts.exists():
        return {}
   
    account_data = [(a.display_name, a.id, a.yesterday_balance, a.cur_balance, a.cur_cash_balance, a.cur_balance-a.yesterday_balance) for a in accounts ]

    names,ids, sod,cur,cur_cash,change = list(zip(*account_data))

    total_data = [('Total', sum(sod), sum(cur), sum(cur_cash), sum(change))]

    exchange_live = 1/Currency.objects.get(code='USD').live_price
    exchange_yesterday = 1/Currency.objects.get(code='USD').GetRateOnDay(datetime.date.today() - datetime.timedelta(days=1))
    exchange_delta = (exchange_live - exchange_yesterday) / exchange_yesterday

    context = {'account_data':account_data, 'total_data':total_data, 'exchange_live':exchange_live, 'exchange_delta':exchange_delta }
    return context

def GeneratePlot(user):
    pairs = GetHistoryValues(user, datetime.date.today() - datetime.timedelta(days=30))
    dates, vals = list(zip(*pairs))
    trace = go.Scatter(name='Total', x=dates, y=vals, mode='lines+markers')
    plotly_url = plotly.plotly.plot([trace], filename='portfolio-values-short-{}'.format(user.username), auto_open=False)
    user.userprofile.plotly_url = plotly_url    
    user.userprofile.save()

@login_required
def Portfolio(request):
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
    return render(request, 'finance/portfolio.html', overall_context)

@login_required
def History(request):
    df = GetValueDataFrame(request.user)

    context = {
        'names': df.columns,
        'rows': df.itertuples(),
    }

    return render(request, 'finance/history.html', context)

from finance.models import Allocation

@login_required
def Rebalance(request):
    securities = Security.objects.with_prices(request.user)
    total_value = sum([s.value for s in securities])

    allocs = list(request.user.allocations.all().prefetch_related('securities'))
    for alloc in allocs:
        alloc.current_amt = sum([s.value for s in securities if s in alloc.securities.all()])
        alloc.current_pct = alloc.current_amt / total_value
        alloc.desired_amt = alloc.desired_pct * total_value
        alloc.buysell = alloc.desired_amt - alloc.current_amt
           

    context = {
        'allocs': allocs,
    }

    return render(request, 'finance/rebalance.html', context)

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
    security = Security.objects.get(symbol=symbol)
    activities = security.activities.filter(
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

                                
        for s, amt in act.GetHoldingEffect().items():
            if s.symbol==symbol:
                totalqty += amt
        
        act.totalqty = totalqty     

        totalacb += act.acbchange
        totalacb = max(0, totalacb)
        act.totalacb = totalacb
        act.acbpershare = act.totalacb / act.totalqty if totalqty else 0

    
    pendinggain = security.live_price_cad*totalqty - totalacb

    context = {'activities':activities, 'symbol':symbol, 'pendinggain': pendinggain}
    return render(request, 'finance/security.html', context)    


def index(request):
    context = {}
    last_update_days = SecurityPrice.objects.filter(
            day__gt=datetime.date.today()-datetime.timedelta(days=30)
        ).order_by('security', '-day').distinct('security').filter(
            security__holdings__enddate=None, security__holdings__account__client__user=request.user
        ).values_list('day', flat=True)
    if any(day < datetime.date.today() for day in last_update_days):
        context['updating'] = True
        result = DailyUpdateTask.delay()

    if request.user.is_authenticated:
        return render(request, 'finance/index.html', context)
    else:
        return redirect('/login/')
