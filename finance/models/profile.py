import datetime
from itertools import groupby

import pendulum
from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.db.models.functions import ExtractYear

from securities.models import Security, SecurityPriceDetail
from utils.misc import plotly_iframe_from_url
from utils.misc import xirr, total_return
from . import Holding, HoldingDetail, BaseAccount, Activity, CostBasis
from ..services import GeneratePortfolioPlots


class UserProfileManager(models.Manager):
    def refresh_graphs(self):
        for profile in self.get_queryset():
            profile.generate_plots()

class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    plotly_url = models.CharField(max_length=500, null=True, blank=True)
    plotly_url2 = models.CharField(max_length=500, null=True, blank=True)
    phone = models.CharField(max_length=32, null=True, blank=True)
    country = models.CharField(max_length=32, null=True, blank=True)

    objects = UserProfileManager()

    @property
    def username(self):
        return self.user.username

    def update_plotly_urls(self, urls):
        self.plotly_url, self.plotly_url2 = urls
        self.save()

    @property
    def portfolio_iframe(self):
        return plotly_iframe_from_url(self.plotly_url)

    @property
    def growth_iframe(self):
        return plotly_iframe_from_url(self.plotly_url2)

    @property
    def current_portfolio_value(self):
        return sum(self.GetHoldingDetails().today()).value

    def generate_plots(self):
        urls = GeneratePortfolioPlots(self)
        self.update_plotly_urls(urls)

    def GetHeldSecurities(self):
        return Holding.objects.for_user(
            self.user).current().values_list('security_id', flat=True).distinct()

    def GetCapGainsSecurities(self):
        only_taxable_accounts = True
        query = Holding.objects.exclude(security__type=Security.Type.Cash
                  ).for_user(self.user).values_list('security_id', flat=True).distinct().order_by('security__symbol')
        if only_taxable_accounts:
            query = query.filter(account__taxable=True)
        return query

    def GetHoldingDetails(self):
        return HoldingDetail.objects.for_user(self.user)

    def GetTaxableHoldingDetails(self):
        return self.GetHoldingDetails().taxable()

    def GetAccounts(self):
        return BaseAccount.objects.for_user(self.user)

    def GetAccount(self, account_id):
        return self.GetAccounts().get(id=account_id)

    def GetActivities(self, only_taxable=False):
        activities = Activity.objects.for_user(self.user)
        if only_taxable:
            activities = activities.taxable()
        return activities

    def AreSecurityPricesUpToDate(self):
        securities = self.GetHeldSecurities()
        prices = SecurityPriceDetail.objects.for_securities(securities).today()
        return securities.count() == prices.count()


    def GetCommissionByYear(self):
        return dict(self.GetActivities().annotate(
            year=ExtractYear('tradeDate')
        ).order_by().values('year').annotate(c=Sum('commission')).values_list('year', 'c'))

    def RateOfReturn(self, start, end, annualized=True):
        deposits = self.GetActivities().between(start+datetime.timedelta(days=1), end).get_all_deposits()
        dates, amounts = (list(zip(*deposits))) if deposits else ([], [])

        start_value = sum(self.GetHoldingDetails().at_date(start)).value
        end_value = sum(self.GetHoldingDetails().at_date(end)).value

        all_dates = (start, *dates, end)
        all_values = (-start_value, *(-dep for dep in amounts), end_value)
        if abs(sum(all_values)) < 1: return 0
        f = xirr if annualized else total_return
        return 100 * f(zip(all_dates, all_values))

    def AllRatesOfReturnFromInception(self, time_period='months'):
        """
        :param time_period: Can be 'days', 'weeks', 'months', 'years'.
        :return:
        """
        inception = pendulum.Date.instance(self.GetInceptionDate())
        period = pendulum.today().date() - inception.add(days=3)
        for day in period.range(time_period):
            yield day, self.RateOfReturn(inception, day)

    def PeriodicRatesOfReturn(self, period_type='months'):
        inception = pendulum.Date.instance(self.GetInceptionDate())
        period = pendulum.today().date() - inception.add(days=3)
        period_type_singular = period_type.rstrip('s')
        for day in period.range(period_type, 1):
            start = max(inception,
                        day.start_of(period_type_singular))
            end = min(pendulum.today().date(),
                      day.end_of(period_type_singular))
            ror = self.RateOfReturn(start, end, annualized=False)
            print (start, end, ror)
            yield end, ror

    def get_capital_gain_summary(self, symbol):
        security = Security.objects.get(symbol=symbol)
        last = CostBasis.objects.for_security(security).for_user(self.user).latest()
        if last.qty_total == 0:
            return {}
        cadprice = security.live_price_cad
        total_value = last.qty_total * cadprice
        pending_gain = cadprice * last.qty_total - last.acb_total
        return {'price' : cadprice,
                'qty' : last.qty_total,
                'acb' : last.acb_total,
                'acb_per_share' : last.acb_per_share,
                'pending_gain' : pending_gain,
                'pending_gain_per_share' : pending_gain / last.qty_total,
                'total_value': total_value,
                'percent_gains' : pending_gain / total_value,
                }

    def GetCapgainsByYear(self):
        costbases = CostBasis.objects.for_user(self.user)
        all_years = list(range(self.GetInceptionDate().year, datetime.date.today().year + 1))
        yearly_data = {s: [0] * len(all_years) for s in costbases.values_list('activity__security_id', flat=True).distinct()}
        year_offset = all_years[0]
        last_acb = {}

        for (sec, year), yearly_bases in groupby(costbases, lambda c: (c.activity.security_id, c.activity.tradeDate.year)):
            for cb in yearly_bases:
                yearly_data[sec][year-year_offset] += cb.capital_gain
                last_acb[sec] = cb.acb_total

        pending_by_security = {}
        for security, value in self.GetTaxableHoldingDetails().today_security_values():
            if security in last_acb:
                pending_by_security[security] = value - last_acb[security]

        return all_years, yearly_data, pending_by_security

    def GetInceptionDate(self):
        return self.GetActivities().earliest().tradeDate

    def GetRebalanceInfo(self, cashadd=0):
        holdings = self.GetHoldingDetails().today()
        total_value = sum(holdings).value + cashadd
        allocs = self.user.allocations.with_rebalance_info(total_value, cashadd)

        missing_holdings = holdings.exclude(security__in=allocs.values_list('securities'))
        missing = []
        for sec, group in groupby(missing_holdings, lambda h: h.security):
            value = sum(group).value
            missing.append({'security': sec,
                            'value': value,
                            'current_pct': value / total_value if total_value else 0})
        return allocs, missing

