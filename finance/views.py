import datetime
from itertools import groupby
from operator import attrgetter
import numpy
import pandas
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.views.generic import DetailView, ListView, TemplateView
from django.views.generic.detail import SingleObjectMixin
from django.views.generic.dates import DateMixin, DayMixin
from django.views.generic.edit import FormView

from securities.models import Security
from utils.misc import plotly_iframe_from_url, partition
from .services import GenerateSecurityPlot, RefreshButtonHandlerMixin
from .tasks import LiveSecurityUpdateTask, SyncActivityTask, SyncSecurityTask
from .models import BaseAccount, Activity, UserProfile, HoldingDetail
from .forms import FeedbackForm


class AccountDetail(LoginRequiredMixin, DetailView):
    model = BaseAccount
    template_name = 'finance/account.html'
    context_object_name = 'account'

    def activities(self):
        return reversed(list(self.object.activities.all()))

    def get_queryset(self):
        return super().get_queryset().for_user(self.request.user)


class AdminSecurity(ListView):
    model = Security
    template_name = 'finance/admin/securities.html'
    context_object_name = 'securities'

    def securities_by_status(self):
        return partition(lambda s: not s.NeedsSync(), self.get_queryset())

    def ajax_request(self, action):
        action, symbol = action.split('-')
        if action == 'sync':
            if symbol == 'all':
                Security.objects.Sync(True)
            else:
                Security.objects.get(pk=symbol).Sync(True)
        return HttpResponse()

    def get_queryset(self):
        return self.model.objects.all().prefetch_related('activities', 'prices').order_by('-type', 'symbol')


class AdminUsers(ListView):
    model = UserProfile
    template_name = 'finance/admin/users.html'
    context_object_name = 'userprofiles'
    ordering = ['user__date_joined']


class AdminAccounts(RefreshButtonHandlerMixin, ListView):
    model = BaseAccount
    template_name = 'finance/admin/accounts.html'
    context_object_name = 'accounts'
    ordering = ['client__user__username']

    def get_queryset(self):
        return super().get_queryset().exclude(client__user__username='guest')

    def ajax_request(self, action):
        action, account_id = action.split('-')
        if action == 'sync':
            BaseAccount.objects.get(pk=account_id).SyncAndRegenerate()
        elif action == 'activities':
            BaseAccount.objects.get(pk=account_id).RegenerateActivities()
        elif action == 'holdings':
            BaseAccount.objects.get(pk=account_id).RegenerateHoldings()
        else:
            raise Http404('Account function does not exist!')
        HoldingDetail.Refresh()
        return HttpResponse()


class UserProfileView(LoginRequiredMixin, TemplateView, FormView):
    model = UserProfile
    template_name = 'finance/userprofile.html'
    context_object_name = 'userprofile'

    def get(self, request, *args, **kwargs):
        self.object = self.request.user.userprofile
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        print(form.cleaned_data['your_name'])
        return super().form_valid(form)


class FeedbackView(FormView):
    template_name = 'finance/feedback.html'
    success_url = '/finance/feedback/?success=true'
    form_class = FeedbackForm

    def get_initial(self):
        self.initial.update({'name': self.request.user.get_full_name(),
                             'email': self.request.user.email})
        return super().get_initial()

    def form_valid(self, form):
        form.send_email()
        return super().form_valid(form)


class CapGainsReport(LoginRequiredMixin, SingleObjectMixin, ListView):
    template_name = 'finance/capgains.html'
    context_object_name = 'symbol'

    def get(self, request, *args, **kwargs):
        self.object = self.get_object(queryset=Security.objects.all())
        return super().get(request, *args, **kwargs)

    def activities(self):
        return self.get_queryset()

    def pending_gain(self):
        last_activity = self.activities()[-1]
        return self.object.pricedetails.latest().cadprice * last_activity.totalqty - last_activity.totalacb

    def get_queryset(self):
        return self.object.activities.for_user(self.request.user).without_dividends().with_capgains_data()


class DividendReport(LoginRequiredMixin, ListView):
    model = Activity
    template_name = 'finance/dividends.html'
    context_object_name = 'activities'

    def by_year(self):
        dividends = self.get_queryset()
        yearly_divs = []
        for year in range(self.request.user.userprofile.GetInceptionDate().year,
                          datetime.date.today().year+1):
            yearly_divs.append((year, sum(dividends.in_year(year).values_list('netAmount', flat=True))))
        return yearly_divs

    def get_queryset(self):
        return super().get_queryset().for_user(self.request.user).dividends()


class SecurityDetail(SingleObjectMixin, ListView):
    model = Security
    paginate_by = 10
    template_name = 'finance/security.html'

    def get(self, request, *args, **kwargs):
        self.object = self.get_object(queryset=Security.objects.all())
        return super().get(request, *args, **kwargs)

    def iframe(self):
        return plotly_iframe_from_url(GenerateSecurityPlot(self.object))

    def get_queryset(self):
        return self.request.user.userprofile.GetActivities().for_security(self.object)


class SnapshotDetail(LoginRequiredMixin, DateMixin, DayMixin, ListView):
    model = Activity
    template_name = 'finance/snapshot.html'
    date_field = 'tradeDate'
    day_format = "%Y-%m-%d"
    context_object_name = 'activities'

    def next_day(self):
        return str(self.get_next_day(self.get_day()) or '')

    def prev_day(self):
        return str(self.get_previous_day(self.get_day()) or '')

    def inception_days_ago(self):
        return (datetime.date.today() - self.request.user.userprofile.GetInceptionDate()).days - 1

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(GetHoldingsContext(self.request.user.userprofile, self.get_day()))
        return context

    def get_day(self):
        try:
           return datetime.datetime.strptime(super().get_day(), self.get_day_format()).date()
        except:
           return datetime.date.today()

    def get_queryset(self):
        return self.request.user.userprofile.GetActivities().at_date(self.get_day())


def GetHoldingsContext(userprofile, as_of_date=None):
    as_of_date = as_of_date or datetime.date.today()

    today_query = userprofile.GetHoldingDetails().at_date(as_of_date).select_related('security', 'account')
    yesterday_query = userprofile.GetHoldingDetails().at_date(as_of_date - datetime.timedelta(days=1)).select_related('security', 'account')
    yesterday_list = list(yesterday_query)
    account_data = []
    for today in today_query:
        yesterday_matches = [y for y in yesterday_query if y.account == today.account and y.security == today.security]
        if yesterday_matches:
            account_data.append(today-yesterday_matches[0])
            yesterday_list.remove(yesterday_matches[0])
        else:
            # We bought this security today.
            account_data.append(today - 0)

    # Check yesterday's holdings to see if there were any that we haven't processed yet (ie sold today)
    for yesterday in yesterday_list:
        account_data.append(0 - yesterday)


    holding_data = []
    for security, holdings in groupby(account_data, lambda h: h.security):
        h = sum(holdings)
        h.account_data = [d for d in account_data if d.security == security]
        holding_data.append(h)

    holding_data = sorted(holding_data, key=attrgetter('security'))
    holding_data, cash_data = partition(lambda h: h.security_type==Security.Type.Cash, holding_data)

    context = {'holding_data': holding_data,
               'cash_data': cash_data,
               'total': sum(account_data) }

    today_balances = dict(today_query.today_account_values())
    yesterday_balances = dict(yesterday_query.yesterday_account_values())
    today_cash_balances = dict(today_query.cash().today_account_values())

    accounts = {
        acc: {
            'id' : BaseAccount.objects.get(display_name=acc).id,
            'cur_balance' : today_balance,
            'yesterday_balance' : yesterday_balances.get(acc, 0),
            'cur_cash_balance' : today_cash_balances.get(acc, 0),
            'today_balance_change' : today_balance - yesterday_balances.get(acc, 0)
        }
        for acc, today_balance in today_balances.items()
    }
    context['accounts'] = accounts
    from collections import defaultdict
    total = defaultdict(int)
    for acc, d in accounts.items():
        for key in ['cur_balance', 'yesterday_balance', 'cur_cash_balance', 'today_balance_change']:
            total[key] += d[key]
    context['account_total'] = total

    exchange_live, exchange_delta = Security.objects.get(symbol='USD').GetTodaysChange()
    context.update({'exchange_live': exchange_live, 'exchange_delta': exchange_delta})

    return context


@login_required
def Portfolio(request):
    userprofile = request.user.userprofile
    if not userprofile.portfolio_iframe:
        userprofile.GeneratePlots()

    if not userprofile.AreSecurityPricesUpToDate():
        SyncSecurityTask.delay(False)
        return render(request, 'finance/index.html', {'updating':True})

    if request.is_ajax():
        if 'refresh-account' in request.GET:
            SyncActivityTask(userprofile)
            LiveSecurityUpdateTask()

        elif 'refresh-plot' in request.GET:
            userprofile.GeneratePlots()

    return render(request, 'finance/portfolio.html', GetHoldingsContext(userprofile))


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
             sum(a.current_pct for a in allocs) + sum(s.current_pct for s in missing),
             sum(a.desired_amt for a in allocs),
             sum(a.current_amt for a in allocs) + sum(s.value for s in missing),
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

    # TODO: Disable security plotly because I am hitting my free chart limit.
    #filename = GenerateSecurityPlot(security)
    iframe = ''#plotly_iframe_from_url(filename)

    activities = request.user.userprofile.GetActivities().for_security(symbol)

    context = {'activities': activities, 'symbol': symbol, 'iframe': iframe}
    return render(request, 'finance/security.html', context)


@login_required
def index(request):
    context = {}
    if not request.user.userprofile.AreSecurityPricesUpToDate():
        context['updating'] = True
        SyncSecurityTask.delay(False)

    if request.user.is_authenticated:
        return render(request, 'finance/index.html', context)
    else:
        return redirect('/login/')
