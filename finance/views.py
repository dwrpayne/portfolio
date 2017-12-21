import datetime
from decimal import Decimal

import numpy
import pandas
from django.contrib.auth.decorators import login_required
from django.db.models import F, Sum
from django.http import HttpResponse
from django.shortcuts import redirect, render

from utils.misc import plotly_iframe_from_url
from .models import BaseAccount, HoldingDetail
from securities.models import Security, SecurityPrice
from .services import GetRebalanceInfo, GeneratePlot, GenerateSecurityPlot
from .tasks import LiveSecurityUpdateTask, SyncActivityTask


def GetHoldingsContext(user):
    holdings_query = HoldingDetail.objects.for_user(user).date_range(
        datetime.date.today() - datetime.timedelta(days=1),
        datetime.date.today()
    )

    total_vals = holdings_query.total_values()
    (_, yesterday_value), (_, today_value) = total_vals
    total_gain = today_value - yesterday_value

    holdings = holdings_query.by_security()
    holdings_byacc = holdings_query.by_security(True)

    def extract_today_with_deltas(holding_list):
        todays = []
        for yesterday, today in zip(holding_list[::2], holding_list[1::2]):
            today['price_delta'] = today['price'] - yesterday['price']
            today['percent_gain'] = today['price_delta'] / yesterday['price']
            today['value_delta'] = today['total_val'] - yesterday['total_val']
            today['percent'] = today['total_val'] / today_value * 100
            todays.append(today)
        return todays

    holding_data = extract_today_with_deltas(holdings)
    account_data = extract_today_with_deltas(holdings_byacc)
    for h in holding_data:
        h['account_data'] = [d for d in account_data if d['security'] == h['security']]

    holding_data.sort(key=lambda r: r['total_val'], reverse=True)

    total = [(total_gain, total_gain / today_value, today_value)]
    context = {'holding_data': holding_data, 'total': total}
    return context


def GetBalanceContext(user):
    accounts = BaseAccount.objects.for_user(user)
    if not accounts.exists():
        return {}

    total = accounts.get_balance_totals()
    exchange_live, exchange_delta = Security.objects.get(symbol='USD').GetTodaysChange()

    context = {'accounts': accounts, 'account_total': total,
               'exchange_live': exchange_live, 'exchange_delta': exchange_delta}
    return context


@login_required
def Portfolio(request):
    if not request.user.userprofile.portfolio_iframe:
        GeneratePlot(request.user)

    if request.is_ajax():
        if 'refresh-live' in request.GET:
            LiveSecurityUpdateTask()

        elif 'refresh-plot' in request.GET:
            GeneratePlot(request.user)

        elif 'refresh-account' in request.GET:
            SyncActivityTask(request.user)
            LiveSecurityUpdateTask()

    overall_context = {**GetHoldingsContext(request.user), **GetBalanceContext(request.user)}
    return render(request, 'finance/portfolio.html', overall_context)


@login_required
def History(request, period):
    holdings = HoldingDetail.objects.for_user(request.user)
    if period == 'year':
        holdings = holdings.year_end()
    elif period == 'month':
        holdings = holdings.month_end()

    vals = holdings.account_values()

    array = numpy.rec.array(list(vals), dtype=[('account', 'S20'), ('day', 'S10'), ('val', 'f4')])
    df = pandas.DataFrame(array)
    table = df.pivot_table(index='day', columns='account', values='val', fill_value=0)
    rows = table.iloc[::-1].iterrows()

    context = {
        'names': list(table.columns) + ['Total'],
        'rows': ((date, vals, sum(vals)) for date, vals in rows),
    }

    return render(request, 'finance/history.html', context)


@login_required
def Rebalance(request):
    allocs, missing = GetRebalanceInfo(request.user)

    total = [sum(a.desired_pct for a in allocs),
             sum(a.current_pct for a in allocs) + sum(s['current_pct'] for s in missing),
             sum(a.desired_amt for a in allocs),
             sum(a.current_amt for a in allocs) + sum(s['total_val'] for s in missing),
             sum(a.buysell for a in allocs),
             ]

    context = {
        'allocs': allocs,
        'missing': missing,
        'total': total
    }

    return render(request, 'finance/rebalance.html', context)


@login_required
def accountdetail(request, account_id):
    account = BaseAccount.objects.get(id=account_id)
    if not account.client.user == request.user:
        return HttpResponse('Unauthorized', status=401)

    activities = reversed(list(account.activities.all()))

    context = {'account': account, 'activities': activities}
    return render(request, 'finance/account.html', context)


@login_required
def securitydetail(request, symbol):
    security = Security.objects.get(symbol=symbol)
    filename = GenerateSecurityPlot(security)
    iframe = plotly_iframe_from_url(filename)
    activities = reversed(list(security.activities.filter(account__client__user=request.user)))

    context = {'activities': activities, 'symbol': symbol, 'iframe': iframe}
    return render(request, 'finance/security.html', context)


@login_required
def capgains(request, symbol):
    security = Security.objects.get(symbol=symbol)
    activities = security.activities.for_user(request.user).taxable().without_dividends().annotate(
        exch=Sum(F('security__currency__rates__price')))

    totalqty = Decimal('0')
    totalacb = Decimal('0')
    activities = list(activities)
    for act in activities:

        act.cadprice = act.exch * act.price
        if not act.cadprice:
            act.cadprice = act.security.GetPriceCAD(act.tradeDate)

        prevacbpershare = totalacb / totalqty if totalqty else 0

        act.capgain = 0
        if act.qty < 0:
            act.capgain = (act.cadprice * abs(act.qty)) - act.commission - (prevacbpershare * abs(act.qty))

        if act.qty > 0:
            act.acbchange = act.cadprice * act.qty + act.commission
        else:
            act.acbchange = -prevacbpershare * abs(act.qty)

        for s, amt in act.GetHoldingEffects().items():
            if s.symbol == symbol:
                totalqty += amt

        act.totalqty = totalqty

        totalacb += act.acbchange
        totalacb = max(0, totalacb)
        act.totalacb = totalacb
        act.acbpershare = act.totalacb / act.totalqty if totalqty else 0

    pendinggain = security.live_price_cad * totalqty - totalacb

    context = {'activities': activities, 'symbol': symbol, 'pendinggain': pendinggain}
    return render(request, 'finance/capgains.html', context)


@login_required
def index(request):
    context = {}
    last_update_days = SecurityPrice.objects.filter(
        day__gt=datetime.date.today() - datetime.timedelta(days=30)
    ).order_by('security', '-day').distinct('security').filter(
        security__holdings__enddate=None, security__holdings__account__client__user=request.user
    ).values_list('day', flat=True)
    if any(day < datetime.date.today() for day in last_update_days):
        context['updating'] = True
        LiveSecurityUpdateTask.delay()

    if request.user.is_authenticated:
        return render(request, 'finance/index.html', context)
    else:
        return redirect('/login/')
