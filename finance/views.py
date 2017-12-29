import datetime
from decimal import Decimal

import numpy
import pandas
import pendulum
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from django.views.generic import DetailView, ListView

from securities.models import Security, SecurityPriceDetail
from utils.misc import plotly_iframe_from_url
from .services import GeneratePortfolioPlots, GenerateSecurityPlot
from .tasks import LiveSecurityUpdateTask, SyncActivityTask
from .models import BaseAccount


class SecurityList(ListView):
    model = Security


class AccountDetail(DetailView):
    model = BaseAccount
    template_name = 'finance/account.html'
    context_object_name = 'account'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['activities'] = reversed(list(self.object.activities.all()))
        return context

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.for_user(self.request.user)


def GetHoldingsContext(userprofile, as_of_date=None):
    as_of_date = as_of_date or datetime.date.today()
    holdings_query = userprofile.GetHoldingDetails().between(
        as_of_date - datetime.timedelta(days=1),
        as_of_date
    )

    total_vals = holdings_query.total_values()
    (_, yesterday_value), (_, today_value) = total_vals
    total_gain = today_value - yesterday_value

    holdings = holdings_query.group_by_security()

    def extract_today_with_deltas(holding_list):
        todays = []
        for h in holding_list:
            if not 'total_val' in h: h['total_val'] = h['value']
        for yesterday, today in zip(holding_list[::2], holding_list[1::2]):
            today['price_delta'] = today['price'] - yesterday['price']
            today['percent_gain'] = today['price_delta'] / yesterday['price']
            today['value_delta'] = today['total_val'] - yesterday['total_val']
            today['percent'] = today['total_val'] / today_value * 100
            todays.append(today)
        return todays

    holding_data = extract_today_with_deltas(holdings)
    account_data = extract_today_with_deltas(holdings_query.
                                             order_by('security', 'account', 'day').
                                             values())
    for h in holding_data:
        h['account_data'] = [d for d in account_data if d['security_id'] == h['security']]

    holding_data.sort(key=lambda r: r['total_val'], reverse=True)

    total = [(total_gain, total_gain / today_value, today_value)]
    context = {'holding_data': holding_data, 'total': total}
    return context


def GetBalanceContext(userprofile):
    accounts = userprofile.GetAccounts()
    if not accounts.exists():
        return {}

    total = accounts.get_balance_totals()
    exchange_live, exchange_delta = Security.objects.get(symbol='USD').GetTodaysChange()

    context = {'accounts': accounts, 'account_total': total,
               'exchange_live': exchange_live, 'exchange_delta': exchange_delta}
    return context


@login_required
def Portfolio(request):
    userprofile = request.user.userprofile
    if not userprofile.portfolio_iframe:
        GeneratePortfolioPlots(userprofile)

    if not userprofile.AreSecurityPricesUpToDate():
        LiveSecurityUpdateTask.delay()
        return render(request, 'finance/index.html', {'updating':True})

    if request.is_ajax():
        if 'refresh-live' in request.GET:
            LiveSecurityUpdateTask()

        elif 'refresh-plot' in request.GET:
            urls = GeneratePortfolioPlots(userprofile)
            userprofile.update_plotly_urls(urls)

        elif 'refresh-account' in request.GET:
            SyncActivityTask(userprofile)
            LiveSecurityUpdateTask()

    overall_context = {**GetHoldingsContext(userprofile), **GetBalanceContext(userprofile)}
    return render(request, 'finance/portfolio.html', overall_context)


@login_required
def History(request, period):
    holdings = request.user.userprofile.GetHoldingDetails()
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
    cashadd = int(request.GET.get('cashadd', 0))
    allocs, missing = request.user.userprofile.GetRebalanceInfo(cashadd)

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
def securitydetail(request, symbol):
    security = Security.objects.get(symbol=symbol)
    filename = GenerateSecurityPlot(security)
    iframe = plotly_iframe_from_url(filename)
    activities = request.user.userprofile.GetActivities().for_security(symbol)

    context = {'activities': activities, 'symbol': symbol, 'iframe': iframe}
    return render(request, 'finance/security.html', context)


@login_required
def capgains(request, symbol):
    activities = list(request.user.userprofile.GetActivities().for_security(symbol).taxable().without_dividends().with_capgains_data())
    last_activity = activities[-1]
    pendinggain = SecurityPriceDetail.objects.for_security(symbol).latest().cadprice * last_activity.totalqty - last_activity.totalacb

    context = {'activities': activities, 'symbol': symbol, 'pendinggain': pendinggain}
    return render(request, 'finance/capgains.html', context)

@login_required
def Snapshot(request):
    day = request.GET.get('day', None)
    day = pendulum.parse(day).date() if day else pendulum.Date.today()
    context = GetHoldingsContext(request.user.userprofile, day)
    age_in_days = (datetime.date.today() - request.user.userprofile.GetInceptionDate()).days
    context['inception_days_ago'] = age_in_days - 1
    context['day'] = day
    context['activities'] = request.user.userprofile.GetActivities().at_date(day)
    return render(request, 'finance/snapshot.html', context)

@login_required
def index(request):
    context = {}
    if not request.user.userprofile.AreSecurityPricesUpToDate():
        context['updating'] = True
        LiveSecurityUpdateTask.delay()

    if request.user.is_authenticated:
        return render(request, 'finance/index.html', context)
    else:
        return redirect('/login/')
