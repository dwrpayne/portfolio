from django.shortcuts import redirect, render
from django.http import HttpResponse
from django.db.models.aggregates import Sum
from django.db.models import F, Q, Sum
from django.contrib.auth.decorators import login_required

from .models import BaseAccount, DataProvider, Holding, Security, SecurityPrice, Currency, Allocation, Activity
from .tasks import GetLiveUpdateTaskGroup, DailyUpdateTask
import datetime
from collections import defaultdict
from decimal import Decimal
import plotly
import plotly.graph_objs as go
import simplejson

def GetHoldingsContext(user):
    total_value = Holding.objects.current().owned_by(user).value_as_of(datetime.date.today())
    total_yesterday = Holding.objects.current().owned_by(user).value_as_of(datetime.date.today() - datetime.timedelta(days=1))
    total_gain = total_value - total_yesterday

    holding_data = Security.objects.get_todays_changes(user)
    account_data = Security.objects.get_todays_changes(user, True)
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
    pairs = SecurityPrice.objects.get_history(user)
    dates, vals = list(zip(*pairs))
    trace = go.Scatter(name='Total', x=dates, y=vals, mode='lines+markers')

    deposits = Activity.objects.filter(account__client__user=user)
    f = Q(type=Activity.Type.Deposit)
    if user.username=='amie':
        f = f | Q(type=Activity.Type.Transfer) | Q(type=Activity.Type.Buy)

    deposits = deposits.filter(f).values_list('tradeDate', 'netAmount')
    dates, amounts = list(zip(*list(deposits)))

    running_totals = []
    total = 0
    for a in amounts:
        total += a
        running_totals.append(total)


    trace2 = go.Scatter(name='Deposits', x=dates, y=running_totals, mode='lines+markers')

    plotly_url = plotly.plotly.plot([trace, trace2], filename='portfolio-values-short-{}'.format(user.username), auto_open=False)
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
    vals_list = SecurityPrice.objects.get_history(request.user, by_account=True)
    accounts = BaseAccount.objects.filter(client__user=request.user)
    ids = accounts.values_list('id', flat=True)
    rows = defaultdict(lambda:{id:0 for id in ids})
    for d,a,v in reversed(vals_list):
        rows[d][a]=v

    context = {
        'names': [a.display_name for a in accounts],
        'rows': rows.items(),
    }

    return render(request, 'finance/history.html', context)

@login_required
def Rebalance(request):
    allocs, missing = Allocation.objects.get_rebalance_info(request.user)

    total = [sum(a.desired_pct for a in allocs),
             sum(a.current_pct for a in allocs),
             sum(a.desired_amt for a in allocs),
             sum(a.current_amt for a in allocs),
             sum(a.buysell for a in allocs),
             ]

    context = {
        'allocs': allocs,
        'missing': missing,
        'total' : total
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

@login_required
def securitydetail(request, symbol):
    security = Security.objects.get(symbol=symbol)
    activities = security.activities.filter(
        account__client__user=request.user, account__taxable=True, security__currency__rates__day=F('tradeDate')
        ).exclude(type=Activity.Type.Dividend).order_by('tradeDate').annotate(exch=Sum(F('security__currency__rates__price')))

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

@login_required
def index(request):
    context = {}
    last_update_days = SecurityPrice.objects.filter(
            day__gt=datetime.date.today()-datetime.timedelta(days=30)
        ).order_by('security', '-day').distinct('security').filter(
            security__holdings__enddate=None, security__holdings__account__client__user=request.user
        ).values_list('day', flat=True)
    if any(day < datetime.date.today() for day in last_update_days):
        context['updating'] = True
        DailyUpdateTask.delay()

    if request.user.is_authenticated:
        return render(request, 'finance/index.html', context)
    else:
        return redirect('/login/')
