import datetime
import os
from itertools import groupby

import numpy
import pandas
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.db.models import Sum
from django.shortcuts import redirect
from django.shortcuts import render, HttpResponseRedirect
from django.views.generic import DetailView, ListView, TemplateView
from django.views.generic.dates import DateMixin, DayMixin
from django.views.generic.edit import FormView, UpdateView

from securities.models import Security
from utils.misc import partition, window
from .forms import FeedbackForm, AccountCsvForm, ProfileInlineFormset
from .forms import UserForm, AllocationForm, AllocationFormSet
from .models import BaseAccount, Activity, UserProfile, HoldingDetail, CostBasis, Holding
from .services import RefreshButtonHandlerMixin, get_growth_data
from .tasks import LiveSecurityUpdateTask, SyncActivityTask, SyncSecurityTask, HandleCsvUpload


def check_for_missing_securities(request):
    current = Holding.objects.current().values_list('security_id').distinct()
    num_prices = current.filter(security__prices__day=datetime.date.today()).count()
    if current.count() > num_prices:
        messages.warning(request, 'Currently updating out-of-date stock data. Please try again in a few seconds.'.format(num_prices, current.count()))
        messages.debug(request, '{} of {} synced'.format(num_prices, current.count()))
        SyncSecurityTask.delay(False)


class AccountDetail(LoginRequiredMixin, DetailView):
    model = BaseAccount
    template_name = 'finance/account.html'
    context_object_name = 'account'

    def activities(self):
        return reversed(list(self.object.activities.all()))

    def get_queryset(self):
        return super().get_queryset().for_user(self.request.user)


class SecurityDetail(LoginRequiredMixin, DetailView):
    model = Security
    template_name = 'finance/security.html'
    context_object_name = 'security'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        activities = self.object.activities.for_user(self.request.user).select_related('account')
        context['activities'] = list(activities.order_by('-trade_date'))
        return context


class AccountCsvUpload(LoginRequiredMixin, FormView):
    form_class = AccountCsvForm
    success_url = '/finance/uploadcsv/'
    template_name = 'finance/uploadcsv.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_invalid(self, form):
        messages.error(self.request,
                       'An error occurred and your file did not successfully upload. \n'
                       'Please let the staff know using the Feedback link at top.')

    def form_valid(self, form):
        accountcsv = form.save(commit=False)
        accountcsv.user = self.request.user
        accountcsv.find_matching_account()
        accountcsv.save()
        messages.success(self.request,
                         'Your file was successfully uploaded and will be processed shortly.'.format(os.path.basename(accountcsv.csvfile.name)))
        HandleCsvUpload.delay(accountcsv.pk)
        return super().form_valid(form)


class AdminSecurity(RefreshButtonHandlerMixin, ListView):
    model = Security
    template_name = 'finance/admin/securities.html'
    context_object_name = 'securities'

    def ajax_request(self, request, action):
        action, symbol = action.split('-')
        if action == 'sync':
            if symbol == 'all':
                Security.objects.Sync(False)
            elif symbol == 'active':
                Security.objects.Sync(True)
            else:
                security = Security.objects.get(pk=symbol)
                security.SyncRates(True)
                return render(request, 'finance/admin/securityrow.html', {'security': security})
        return HttpResponse()

    def get_queryset(self):
        return self.model.objects.all().prefetch_related('activities', 'prices').order_by('-type', 'symbol')


class UserProfileView(LoginRequiredMixin, UpdateView):
    model = get_user_model()
    template_name = 'finance/userprofile.html'
    form_class = UserForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['formset'] = ProfileInlineFormset(data=self.request.POST or None, instance=self.request.user)
        context['pass_form'] = PasswordChangeForm(self.request.user, data=self.request.POST or None)
        return context

    def get(self, request, *args, **kwargs):
        if not request.user.pk == int(kwargs.get('pk', -1)):
            raise PermissionDenied
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        if 'profile' in self.request.POST:
            created_user = form.save(commit=False)
            formset = ProfileInlineFormset(data=self.request.POST, instance=self.request.user)
            if formset.is_valid():
                created_user.save()
                formset.save()
                messages.success(self.request, 'Your profile was successfully updated!')
                return HttpResponseRedirect(self.request.path)

        elif 'password' in self.request.POST:
            if form.is_valid():
                form.save()
                messages.success(self.request, 'Your password was successfully updated!')
                return HttpResponseRedirect(self.request.path)
        # TODO: Messages here!
        return HttpResponseRedirect(self.request.path)


class UserPasswordPost(LoginRequiredMixin, UpdateView):
    model = get_user_model()
    form_class = PasswordChangeForm
    template_name = 'finance/userprofile.html'

    def get(self, request, *args, **kwargs):
        self.object = None
        return super().get(self, request, *args, **kwargs)

    def get_form(self, form_class=None):
        kwargs = self.get_form_kwargs()
        kwargs.pop('instance')
        return PasswordChangeForm(self.request.user, **kwargs)

    def post(self, request, *args, **kwargs):
        if not request.user.pk == int(kwargs.get('pk', -1)):
            raise PermissionDenied
        return super().post(request, *args, **kwargs)


class AdminUsers(ListView):
    model = UserProfile
    template_name = 'finance/admin/users.html'
    context_object_name = 'userprofiles'
    ordering = ['user__date_joined']


class AdminAccounts(RefreshButtonHandlerMixin, ListView):
    model = BaseAccount
    template_name = 'finance/admin/accounts.html'
    context_object_name = 'accounts'
    ordering = ['user__username']

    def ajax_request(self, request, action):
        action, account_pk = action.split('-')
        if action == 'sync':
            BaseAccount.objects.get(pk=account_pk).SyncAndRegenerate()
        elif action == 'activities':
            BaseAccount.objects.get(pk=account_pk).RegenerateActivities()
        elif action == 'holdings':
            BaseAccount.objects.get(pk=account_pk).RegenerateHoldings()
        else:
            raise Http404('Account function does not exist!')
        HoldingDetail.Refresh()
        return HttpResponse()


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
        messages.success(self.request, "Thank you for your input! It is greatly appreciated.")
        return super().form_valid(form)


class CapGainsSecurityReport(LoginRequiredMixin, ListView):
    model = CostBasis
    template_name = 'finance/capgainsdetail.html'
    context_object_name = 'costbases'

    def get_queryset(self):
        self.symbol = self.kwargs.get('pk')
        self.summary = self.request.user.userprofile.get_capital_gain_summary(self.symbol)
        self.costbases = super().get_queryset().for_security(self.symbol).for_user(self.request.user)
        return self.costbases


class CapGainsReport(LoginRequiredMixin, TemplateView):
    template_name = 'finance/capgains.html'

    def get(self, request, *args, **kwargs):
        self.years, self.yearly_gains, self.pending_by_security = request.user.userprofile.GetCapgainsByYear()
        self.total_gains = []
        for i, year in enumerate(self.years):
            self.total_gains.append(sum(gains[i] for gains in self.yearly_gains.values()))
        self.total_pending = sum(self.pending_by_security.values())
        self.summary_by_security = {security: request.user.userprofile.get_capital_gain_summary(security)
                                    for security,pending_gain in self.pending_by_security.items()}
        return super().get(self, request, *args, **kwargs)


class DividendReport(LoginRequiredMixin, ListView):
    model = Activity
    template_name = 'finance/dividends.html'
    context_object_name = 'activities'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dividends = self.get_queryset()
        years = sorted(list(dt.year for dt in dividends.dates('trade_date', 'year')))
        securities = dividends.security_list()

        security_year_amounts = {s : [0]*len(years) for s in securities}
        for sec, divs in groupby(dividends.order_by('security_id', 'trade_date'), lambda div: div.security_id):
            for d in divs:
                security_year_amounts[sec][d.trade_date.year-years[0]] += d.net_amount
            security_year_amounts[sec].append(sum(security_year_amounts[sec]))

        context['security_year_amounts'] = sorted(security_year_amounts.items())
        context['years'] = years
        context['yearly_totals'] = [sum(yearly_vals[i-years[0]] for yearly_vals in security_year_amounts.values()) for i in years]
        context['total'] = sum(context['yearly_totals'])
        return context

    def get_queryset(self):
        return super().get_queryset().for_user(self.request.user).dividends().taxable()


class SnapshotDetail(LoginRequiredMixin, DateMixin, DayMixin, ListView):
    model = Activity
    template_name = 'finance/snapshot.html'
    date_field = 'trade_date'
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


class RebalanceView(LoginRequiredMixin, FormView):
    template_name = 'finance/rebalance.html'
    form_class = AllocationForm

    def get_filled_allocations(self, cashadd=0):
        return self.request.user.userprofile.GetRebalanceInfo(cashadd)

    def get_context_data(self, **kwargs):
        cashadd = int(self.request.GET.get('cashadd', 0))
        allocs, leftover = self.get_filled_allocations(cashadd)

        context = super().get_context_data(**kwargs)
        context['formset'] = AllocationFormSet(queryset=allocs)
        context['cashadd'] = cashadd
        context.update( {'allocs': allocs, 'leftover': leftover} )

        total = sum(a.desired_pct for a in allocs)
        context['unassigned_pct'] = 100 - total
        if total < 100 and not leftover:
            messages.warning(self.request, 'Your allocation percentages only total to {}. Your numbers will be inaccurate until you fix this!'.format(total))

        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        if 'form-add' not in self.request.POST:
            kwargs['empty_permitted'] = True
        return kwargs

    def post(self, request, *args, **kwargs):
        if 'form-add' in request.POST:
            return super().post(request, *args, **kwargs)
        else:
            form = AllocationFormSet(self.request.POST)
            if form.is_valid():
                return self.formset_valid(form)
            else:
                return self.form_invalid(form)

    def form_invalid(self, form):
        if 'formset-modify' in self.request.POST:
            for error in form.non_form_errors():
                messages.error(self.request, error)
            for errorlist in form.errors:
                for error in errorlist:
                    messages.error(self.request, error)
        else:
            for error in form.errors:
                messages.error(self.request, error)

        return render(self.request, self.template_name, self.get_context_data())

    def formset_valid(self, form):
        form.save()
        return render(self.request, self.template_name, self.get_context_data())

    def form_valid(self, form):
        allocationform = form.save(commit=False)
        allocationform.user = self.request.user
        allocationform.save()
        form.save_m2m()
        return render(self.request, self.template_name, self.get_context_data())


def GetHoldingsContext(userprofile, as_of_date=None):
    as_of_date = as_of_date or datetime.date.today()

    today_query = userprofile.GetHoldingDetails().at_date(as_of_date).select_related('security', 'account')
    yesterday_query = userprofile.GetHoldingDetails().at_date(as_of_date - datetime.timedelta(days=1)).select_related('security', 'account')
    account_data = {(h.security_id, h.account_id) : 0 for h in list(today_query) + list(yesterday_query)}
    for h in today_query:
        account_data[(h.security_id, h.account_id)] += h
    for h in yesterday_query:
        account_data[(h.security_id, h.account_id)] -= h
    account_data = account_data.values()

    holding_data = []
    for security, holdings in groupby(account_data, lambda h: h.security):
        h = sum(holdings)
        h.account_data = [d for d in account_data if d.security == security]
        holding_data.append(h)

    # Sort by currency first, then symbol. Keep cash at the end (currency = '')
    holding_data = sorted(holding_data, key=lambda h: (h.security.currency or 'ZZZ', h.security.symbol))
    cash_types = Security.cash.values_list('symbol', flat=True)
    holding_data, cash_data = partition(lambda h: h.security in cash_types, holding_data)

    context = {'holding_data': holding_data,
               'cash_data': cash_data,
               'total': sum(account_data) }

    today_balances = dict(today_query.today_account_values())
    yesterday_balances = dict(yesterday_query.yesterday_account_values())
    today_cash_balances = dict(today_query.cash().today_account_values())

    accounts = {
        BaseAccount.objects.get(pk=id).display_name: {
            'id' : id,
            'cur_balance' : today_balance,
            'cur_cash_balance' : today_cash_balances.get(id, 0),
            'today_balance_change' : today_balance - yesterday_balances.get(id, 0)
        }
        for id, today_balance in today_balances.items()
    }
    context['accounts'] = accounts
    from collections import defaultdict
    total = defaultdict(int)
    for acc, d in accounts.items():
        for key in ['cur_balance', 'cur_cash_balance', 'today_balance_change']:
            total[key] += d[key]
    context['account_total'] = total

    exchange_live, exchange_delta = Security.objects.get(symbol='USD').GetTodaysChange()
    context.update({'exchange_live': exchange_live, 'exchange_delta': exchange_delta})

    return context


class PortfolioView(LoginRequiredMixin, TemplateView):
    template_name = 'finance/portfolio.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(GetHoldingsContext(self.request.user.userprofile))
        return context


class HistoryDetail(LoginRequiredMixin, ListView):
    template_name = 'finance/history.html'
    model = HoldingDetail
    context_object_name = 'holdings'

    def get_context_data(self, **kwargs):
        vals = self.get_queryset().account_values()

        array = numpy.rec.array(list(vals), dtype=[('account', 'U20'), ('day', 'U10'), ('val', 'f4')])
        df = pandas.DataFrame(array)
        table = df.pivot_table(index='day', columns='account', values='val', fill_value=0)
        rows = table.iloc[::-1].iterrows()

        context = super().get_context_data(**kwargs)
        context = {
            'names': list(table.columns) + ['Total'],
            'rows': ((date, vals, sum(vals)) for date, vals in rows),
        }
        return context

    def get_queryset(self):
        period = self.kwargs['period']
        queryset = self.request.user.userprofile.GetHoldingDetails()
        if period == 'year':
            return queryset.year_end()
        elif period == 'month':
            return queryset.month_end()
        return queryset



def portfolio_chart(request):
    userprofile = request.user.userprofile
    #names = [['Day', 'Total Value', 'Total Contributions', 'Net Growth']]
    return JsonResponse(list(zip(*get_growth_data(userprofile))), safe=False)


def growth_chart(request):
    userprofile = request.user.userprofile
    days, values, deposits, growth = get_growth_data(userprofile)
    daily_growth = [t - y for y, t in window(growth)]
    return JsonResponse(list(zip(days, daily_growth)), safe=False)


def security_chart(request, symbol):
    def to_ts(d):
        return datetime.datetime.combine(d, datetime.time.min).timestamp()*1000
    security = Security.objects.get(symbol=symbol)
    series = []
    series.append({
        'name': 'Price',
        'data': [(to_ts(d), float(p)) for d,p in security.prices.values_list('day', 'price')],
        'color': 'blue',
        'id': 'price'
    })
    # if not security.currency == 'CAD':
    #     series.append({
    #         'name': 'CAD Price',
    #         'data': [(to_ts(d), float(p)) for d,p in pricedetails.values_list('day', 'cadprice')],
    #         'color': 'orange'
    #     })

    userprofile = request.user.userprofile
    activities = userprofile.GetActivities().for_security(security)
    purchase_data = activities.transactions().values('trade_date').annotate(total_qty=Sum('qty'), ).values_list('trade_date', 'total_qty', 'price')
    series.append({
        'name': 'Purchases',
        'type': 'flags',
        'shape': 'squarepin',
        'onSeries': 'price',
        'allowOverlapX': True,
        'data': [{'x': to_ts(day),
                  'fillColor': 'GreenYellow' if qty > 0 else 'red',
                  'title': str(int(qty)),
                  'text': '{} {:.0f} @ {:.2f}'.format('Buy' if qty > 0 else 'Sell', qty, price),
                  } for day, qty, price in purchase_data]
    })
    series.append({
        'name': 'Dividends',
        'type': 'flags',
        'fillColor': 'LightCyan',
        'shape': 'circlepin',
        'allowOverlapX': True,
        'data': [{'x': to_ts(day),
                  'title': '{:.2f}'.format(price),
                  'text': 'Dividend of ${:.2f}'.format(price),
                  } for day, price in activities.dividends().values_list('trade_date', 'price').distinct()]

    })
    return JsonResponse(series, safe=False)


@login_required
def index(request):
    context = {}
    check_for_missing_securities(request)

    if request.user.is_authenticated:
        return render(request, 'finance/index.html', context)
    else:
        return redirect('/login/')

