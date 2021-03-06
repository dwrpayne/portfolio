import datetime
import os
from decimal import Decimal
from itertools import groupby

import numpy
import pandas
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.shortcuts import render, HttpResponseRedirect
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property
from django.views.decorators.cache import never_cache
from django.views.generic import DetailView, ListView, TemplateView
from django.views.generic.dates import DateMixin, DayMixin
from django.views.generic.edit import FormView, UpdateView

from charts.models import GrowthChart, RebalancePieChart, SecurityChart
from charts.views import HighChartMixin
from securities.models import MissingPriceException
from securities.models import Security
from utils.misc import partition
from .forms import FeedbackForm, AccountCsvForm, ProfileInlineFormset
from .forms import UserForm
from .models import BaseAccount, Activity, UserProfile, HoldingDetail, CostBasis
from .services import RefreshButtonHandlerMixin, check_for_missing_securities
from .tasks import HandleCsvUpload


class AccountDetail(LoginRequiredMixin, DetailView):
    model = BaseAccount
    template_name = 'finance/account.html'
    context_object_name = 'account'

    def activities(self):
        return reversed(list(self.object.activities.all()))

    def get_queryset(self):
        return super().get_queryset().for_user(self.request.user)


class SecurityDetail(LoginRequiredMixin, HighChartMixin, DetailView):
    model = Security
    template_name = 'finance/security.html'
    context_object_name = 'security'
    chart_classes = [SecurityChart]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        activities = self.object.activities.for_user(self.request.user).select_related('account')
        context['activities'] = list(activities.order_by('-trade_date'))
        return context

    def get_chart_kwargs(self, request):
        return {'security': self.get_object()}


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
                         'Your file was successfully uploaded and will be processed shortly.'.format(
                             os.path.basename(accountcsv.csvfile.name)))
        HandleCsvUpload.delay(accountcsv.pk)
        return super().form_valid(form)


@method_decorator(never_cache, 'dispatch')
class AdminSecurity(RefreshButtonHandlerMixin, ListView):
    model = Security
    template_name = 'finance/admin/securities.html'
    context_object_name = 'securities'

    def ajax_request(self, request, actions):
        action, symbol = actions
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
        securities = self.model.objects.all().prefetch_related('activities', 'prices', 'datasources').order_by('-type', 'symbol')
        for s in securities:
            try:
                s.earliest_have = s.prices.earliest().day
                s.latest_price = s.prices.latest()
                s.latest_have = s.latest_price.day
                s.need_sync_earlier = (s.earliest_have >= s.earliest_price_needed)
                s.need_sync_later = (s.latest_have < s.latest_price_needed)
                s.current_price = s.latest_price.price
            except:
                pass
        return securities


@method_decorator(never_cache, 'dispatch')
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


@method_decorator(never_cache, 'dispatch')
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


@method_decorator(never_cache, 'dispatch')
class AdminAccounts(RefreshButtonHandlerMixin, ListView):
    model = BaseAccount
    template_name = 'finance/admin/accounts.html'
    context_object_name = 'accounts'
    ordering = ['user__username']

    def ajax_request(self, request, actions):
        action = actions[0]
        if action == 'sync':
            BaseAccount.objects.get(pk=actions[1]).SyncAndRegenerate()
        elif action == 'activities':
            BaseAccount.objects.get(pk=actions[1]).RegenerateActivities()
        elif action == 'holdings':
            BaseAccount.objects.get(pk=actions[1]).RegenerateHoldings()
        elif action == 'holdingdetails':
            HoldingDetail.Refresh()
        else:
            raise Http404('Account function does not exist!')
        return HttpResponse()

    def get_queryset(self):
        return super().get_queryset().select_related('user').with_newest_activity()


@method_decorator(never_cache, 'dispatch')
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
        security = Security.objects.get(symbol=self.symbol)
        self.costbases = CostBasis.objects.get_activities_with_acb(self.request.user, security)
        self.summary = self.request.user.userprofile.get_capital_gain_summary(self.symbol, self.costbases)
        return self.costbases


class CapGainsReport(LoginRequiredMixin, TemplateView):
    template_name = 'finance/capgains.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dataframe = self.request.user.userprofile.get_capgains_summary()
        context['totals'] = dataframe.ix['Total']
        dataframe = dataframe.drop('Total')
        context['columns'] = dataframe.columns
        context['dataframe_dict'] = dataframe.to_dict('i')

        return context


class DividendReport(LoginRequiredMixin, ListView):
    model = Activity
    template_name = 'finance/dividends.html'
    context_object_name = 'activities'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dividends = self.get_queryset()
        years = sorted(list(dt.year for dt in dividends.dates('trade_date', 'year')))
        securities = dividends.security_list()

        security_year_amounts = {s: [0] * len(years) for s in securities}
        for sec, divs in groupby(dividends.order_by('security_id', 'trade_date'), lambda div: div.security_id):
            for d in divs:
                security_year_amounts[sec][d.trade_date.year - years[0]] += d.net_amount
            security_year_amounts[sec].append(sum(security_year_amounts[sec]))

        context['security_year_amounts'] = sorted(security_year_amounts.items())
        context['years'] = years
        context['yearly_totals'] = [sum(yearly_vals[i - years[0]] for yearly_vals in security_year_amounts.values())
                                    for i in years]
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
        try:
            context.update(GetHoldingsContext(self.request.user.userprofile, self.get_day()))
        except MissingPriceException:
            context['error'] = 'No stock prices found in the database for this day, please alert David.'
        context['activity_days'] = self.request.user.userprofile.GetActivities().values_list(
            'trade_date', flat=True).distinct()
        return context

    def get_day(self):
        try:
            return datetime.datetime.strptime(super().get_day(), self.get_day_format()).date()
        except:
            return datetime.date.today()

    def get_queryset(self):
        return self.request.user.userprofile.GetActivities().at_date(self.get_day())


class RebalanceView(LoginRequiredMixin, HighChartMixin, TemplateView):
    template_name = 'finance/rebalance.html'
    chart_classes = [RebalancePieChart]

    def get_filled_allocations(self, cashadd=0):
        return self.request.user.userprofile.GetRebalanceInfo(cashadd)

    def get_context_data(self, **kwargs):
        cashadd = int(self.request.GET.get('cashadd', 0))
        allocs = self.get_filled_allocations(cashadd)

        context = super().get_context_data(**kwargs)
        context['cashadd'] = cashadd
        context.update({'allocs': allocs})

        total = sum(a.desired_pct for a in allocs)
        context['unassigned_pct'] = 100 - total
        if total < 100:
            messages.warning(self.request,
                             'Your allocation percentages only total to {}. Your numbers will be inaccurate until you fix this!'.format(
                                 total))

        return context

    # TODO: This is super ugly, refactor this
    @staticmethod
    def add_to_ret_dict(ret_dict, id, obj):
        if obj:
            ret_dict.setdefault('new-cells', dict())
            ret_dict['new-cells']['{}-current_pct'.format(id)] = obj.current_pct
            ret_dict['new-cells']['{}-desired_amt'.format(id)] = obj.desired_amt
            ret_dict['new-cells']['{}-current_amt'.format(id)] = obj.current_amt
            ret_dict['new-cells']['{}-buysell'.format(id)] = obj.buysell

    def handle_cashadd(self, cashadd):
        allocs = self.get_filled_allocations(cashadd)
        ret_dict = {}
        for alloc in allocs:
            self.add_to_ret_dict(ret_dict, alloc.id, alloc)
        return JsonResponse(ret_dict)

    def handle_desired_pct_change(self, alloc_id, desired_pct):
        from .models import Allocation
        Allocation.objects.filter(pk=alloc_id).update(desired_pct=desired_pct)
        allocs = self.get_filled_allocations()
        alloc = next(a for a in allocs if str(a.id) == alloc_id)
        ret_dict = {}
        if alloc.securities.count() == 0 and desired_pct == 0:
            ret_dict['delete-id'] = alloc.id
            alloc.delete()
        else:
            self.add_to_ret_dict(ret_dict, alloc.id, alloc)

        return JsonResponse(ret_dict)

    def handle_security_move(self, source_id, security, target_id):
        from .models import Allocation
        ret_dict = {}
        if target_id == 'newrow':
            target_id = None
        source_alloc, target_alloc = Allocation.objects.reallocate_security(security, source_id,
                                                                            target_id, self.request.user)
        if not target_id:
            ret_dict['newrow'] = target_id = target_alloc.id
        if source_alloc.securities.count() == 0 and source_alloc.desired_pct==0:
            ret_dict['delete-id'] = source_alloc.id
            source_alloc.delete()
        allocs = self.get_filled_allocations()

        for alloc in allocs:
            if alloc.id in [int(source_id), int(target_id)]:
                self.add_to_ret_dict(ret_dict, alloc.id, alloc)
        return JsonResponse(ret_dict)


    def post(self, request, *args, **kwargs):
        if request.is_ajax():
            input_id = request.POST.get('input_id', '')
            if input_id:
                input_val = request.POST['input_val'] or 0
                if input_id == 'cashadd':
                    return self.handle_cashadd(int(input_val))
                else:
                    alloc_id = input_id.split('-')[0]
                    return self.handle_desired_pct_change(alloc_id, Decimal(input_val))
            else:
                source_alloc = request.POST.get('source_alloc', '')
                security = request.POST['security']
                target_alloc = request.POST['target_alloc']
                return self.handle_security_move(source_alloc, security, target_alloc)

        return super().get(request, *args, **kwargs)


def GetHoldingsContext(userprofile, as_of_date=None):
    as_of_date = as_of_date or datetime.date.today()

    holdingdetails = userprofile.GetHoldingDetails().between(as_of_date - datetime.timedelta(days=1), as_of_date).select_related(
        'security', 'account').order_by('security', 'account', '-day')

    account_data = []
    for (account, security), holdings in groupby(holdingdetails, lambda h: (h.account, h.security)):
        holdings = list(holdings)
        if len(holdings) == 2:
            account_data.append(holdings[0] - holdings[1])
        elif holdings[0].day == as_of_date:
            account_data.append(holdings[0] - 0)
        elif holdings[0].day == as_of_date - datetime.timedelta(days=1):
            account_data.append(0 - holdings[0])
        else:
            raise HoldingDetail.MultipleObjectsReturned
            #messages.error('Database corruption error code 126.')
            #messages.debug('Failed to calculate a holding change for {} {}'.format(account, security))

    book_value_list = userprofile.get_book_value_by_account_security(as_of_date)

    holding_data = []
    for security, holdings in groupby(account_data, lambda h: h.security):
        h = sum(holdings)
        h.account_data = [d for d in account_data if d.security == security]
        h.book_value = 0
        for account_datum in h.account_data:
            try:
                account_datum.book_value = next(-val for a, s, val in book_value_list if account_datum.account.id==a and account_datum.security.symbol==s)
                account_datum.book_value *= account_datum.account.joint_share
                account_datum.total_value_gain = account_datum.value - account_datum.book_value
                h.book_value += account_datum.book_value
            except StopIteration:
                continue
        h.account_data.sort(key=lambda d:d.value, reverse=True)
        if h.book_value:
            h.total_value_gain = h.value - h.book_value
        holding_data.append(h)

    # Sort by currency first, then symbol. Keep cash at the end (currency = '')
    holding_data = sorted(holding_data, key=lambda h: (h.security.currency, h.value), reverse=True)
    cash_types = Security.cash.values_list('symbol', flat=True)
    holding_data, cash_data = partition(lambda h: h.security.symbol in cash_types, holding_data)


    total_holdings = sum(account_data)
    total_holdings.book_value = sum(getattr(a, 'book_value', 0) for a in account_data)
    total_holdings.total_value_gain = total_holdings.value - total_holdings.book_value

    context = {'holding_data': holding_data,
               'cash_data': cash_data,
               'total': total_holdings}

    accounts = {h.account for h in holdingdetails}

    accounts = {
        a.display_name: {
            'id': a.id,
            'cur_balance': sum(h.value for h in holdingdetails
                               if h.account == a and h.day == as_of_date),
            'cur_cash_balance': sum(h.value for h in holdingdetails
                                    if h.account == a and h.day == as_of_date and h.security.symbol in cash_types),
            'today_balance_change': sum(h.value for h in holdingdetails if h.account == a and h.day == as_of_date) - \
                                    sum(h.value for h in holdingdetails if h.account == a and h.day < as_of_date)
        }
        for a in accounts
    }
    context['accounts'] = accounts
    from collections import defaultdict
    total = defaultdict(int)
    for _, d in accounts.items():
        for key in ['cur_balance', 'cur_cash_balance', 'today_balance_change']:
            total[key] += d[key]
    context['account_total'] = total

    exchange_live, exchange_delta = Security.objects.get(symbol='USD').GetTodaysChange()
    context.update({'exchange_live': exchange_live, 'exchange_delta': exchange_delta})

    return context


class PortfolioView(LoginRequiredMixin, HighChartMixin, TemplateView):
    template_name = 'finance/portfolio.html'
    chart_classes = [GrowthChart]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for day in reversed(pandas.date_range(datetime.date.today() - datetime.timedelta(days=7), datetime.date.today())):
            try:
                context.update(GetHoldingsContext(self.request.user.userprofile, day.date()))
                break
            except MissingPriceException:
                context['error'] = f'Stock prices not found for today, using data as of {(day-datetime.timedelta(days=1)).date()}.'
        context['activities'] = self.request.user.userprofile.GetActivities().after(
                            datetime.date.today() - datetime.timedelta(days=90)
                        ).select_related('account')
        return context


class HistoryDetail(LoginRequiredMixin, ListView):
    template_name = 'finance/history.html'
    model = HoldingDetail

    def get_context_data(self, **kwargs):
        vals = self.object_list.account_values()

        array = numpy.rec.array(list(vals), dtype=[('account', 'U20'), ('day', 'U10'), ('val', 'f4')])
        df = pandas.DataFrame(array)
        table = df.pivot_table(index='day', columns='account', values='val', fill_value=0, aggfunc=numpy.sum,
                               margins=True, margins_name='Total')
        table = table.drop('Total')
        rows = table.iloc[::-1].iterrows()

        context = super().get_context_data(**kwargs)
        context['table'] = table
        context['names'] = list(table.columns) + ['Total']
        context['rows'] = ((date, vals, sum(vals)) for date, vals in rows)
        return context

    def get_queryset(self):
        period = self.kwargs['period']
        queryset = self.request.user.userprofile.GetHoldingDetails()
        if period == 'year':
            return queryset.year_end()
        elif period == 'month':
            return queryset.month_end()
        return queryset


@login_required
def index(request):
    context = {}
    check_for_missing_securities(request)

    if request.user.is_authenticated:
        return render(request, 'finance/index.html', context)
    else:
        return redirect('/login/')
