import datetime
from itertools import groupby

import numpy
import pandas
import pendulum
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import DetailView, ListView
from django.views.generic.detail import SingleObjectMixin

from securities.models import Security, SecurityPriceDetail
from utils.misc import plotly_iframe_from_url
from .services import GeneratePortfolioPlots, GenerateSecurityPlot
from .tasks import LiveSecurityUpdateTask, SyncActivityTask
from .models import BaseAccount, Activity, HoldingChange


class AccountDetail(LoginRequiredMixin, DetailView):
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


class CapGainsReport(LoginRequiredMixin, SingleObjectMixin, ListView):
    model = Activity
    template_name = 'finance/capgains.html'

    def get(self, request, *args, **kwargs):
        self.object = self.get_object(queryset=Security.objects.all())
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['symbol'] = self.object

        activities = self.get_queryset()
        context['activities'] = activities
        last_activity = activities[-1]
        context['pendinggain'] = self.object.pricedetails.latest().cadprice * last_activity.totalqty - last_activity.totalacb

        return context

    def get_queryset(self):
        return self.object.activities.for_user(self.request.user).taxable().without_dividends().with_capgains_data()


class DividendReport(LoginRequiredMixin, ListView):
    model = Activity
    template_name = 'finance/dividends.html'
    context_object_name = 'activities'

    def get_context_data(self, **kwargs):
        dividends = self.get_queryset()
        by_year = []
        for year in range(self.request.user.userprofile.GetInceptionDate().year,
                          datetime.date.today().year+1):
            by_year.append((year, sum(dividends.in_year(year).values_list('netAmount', flat=True))))

        context = super().get_context_data(**kwargs)
        context['by_year'] = by_year
        return context

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.for_user(self.request.user).taxable().dividends()


class SecurityDetail(SingleObjectMixin, ListView):
    model = Security
    paginate_by = 10
    template_name = 'finance/security.html'

    def get(self, request, *args, **kwargs):
        self.object = self.get_object(queryset=Security.objects.all())
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        filename = GenerateSecurityPlot(self.object)
        context = super().get_context_data(**kwargs)
        context['iframe'] = plotly_iframe_from_url(filename)
        context['symbol'] = self.object.symbol
        return context

    def get_queryset(self):
        return self.request.user.userprofile.GetActivities().for_security(self.object)


def GetHoldingsContext(userprofile, as_of_date=None):
    as_of_date = as_of_date or datetime.date.today()

    today_query = userprofile.GetHoldingDetails().at_date(as_of_date)
    yesterday_query = userprofile.GetHoldingDetails().at_date(as_of_date - datetime.timedelta(days=1))

    account_data = [t-y for y, t in zip(yesterday_query, today_query)]
    holding_data = []
    for security, holdings in groupby(account_data, lambda h: h.security):
        h = sum(holdings)
        h.account_data = [d for d in account_data if d.security == security]
        holding_data.append(h)

    holding_data.sort(key=lambda r: r.value, reverse=True)

    context = {'holding_data': holding_data, 'total': sum(account_data)}
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
