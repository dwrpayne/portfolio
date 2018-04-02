import datetime

import pendulum
from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.db.models.functions import ExtractYear

from securities.models import Security
from utils.misc import xirr, total_return
from . import Holding, HoldingDetail, BaseAccount, Activity, CostBasis


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    phone = models.CharField(max_length=32, null=True, blank=True)
    country = models.CharField(max_length=32, null=True, blank=True)

    @property
    def username(self):
        return self.user.username

    @property
    def current_portfolio_value(self):
        return sum(self.GetHoldingDetails().today()).value

    def GetHeldSecurities(self):
        return Security.objects.filter(pk__in=self.GetCurrentHoldings().values_list('security')).order_by('-type', 'symbol')

    def GetCurrentHoldings(self):
        return Holding.objects.for_user(self.user).current()

    def GetCapGainsSecurities(self):
        return Holding.objects.for_user(self.user).exclude(security__type=Security.Type.Cash
                    ).values_list('security_id', flat=True).distinct().order_by('security__symbol'
                    ).filter(account__taxable=True)

    def GetHoldingDetails(self):
        return HoldingDetail.objects.for_user(self.user)

    def GetAccounts(self):
        return BaseAccount.objects.for_user(self.user)

    def GetActivities(self, only_taxable=False):
        activities = Activity.objects.for_user(self.user)
        if only_taxable:
            activities = activities.taxable()
        return activities

    def GetCommissionByYear(self):
        return dict(self.GetActivities().annotate(
            year=ExtractYear('trade_date')
        ).order_by().values('year').annotate(c=Sum('commission')).values_list('year', 'c'))

    def RateOfReturn(self, start, end, annualized=True):
        deposits = self.GetActivities().between(start + datetime.timedelta(days=1), end).get_all_deposits()
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
            print(start, end, ror)
            yield end, ror

    def get_capital_gain_summary(self, symbol, acb_activities):
        security = Security.objects.get(symbol=symbol)
        last = acb_activities[-1]
        if last.qty_total == 0:
            return {}
        cadprice = security.live_price_cad
        price = exch = 0
        if not security.currency == 'CAD':
            price = security.live_price
            exch = cadprice / price
        total_value = last.qty_total * cadprice
        pending_gain = cadprice * last.qty_total - last.acb_total
        return {'cadprice': cadprice,
                'price': price,
                'exchange': exch,
                'qty': last.qty_total,
                'acb': last.acb_total,
                'acb_per_share': last.acb_per_share,
                'pending_gain': pending_gain,
                'pending_gain_per_share': pending_gain / last.qty_total,
                'book_value': total_value - pending_gain,
                'total_value': total_value,
                'percent_gains': pending_gain / total_value if total_value else 0,
                }

    def get_capgains_summary(self):
        """
        :return: A pandas.DataFrame containing a capital gains summary by security and year.
        """
        all_years = {year: 0 for year in range(self.GetInceptionDate().year, datetime.date.today().year + 1)}
        realized_by_security_year = {s: dict(all_years) for s in self.GetCapGainsSecurities()}
        last_acb = {}

        import pandas
        df = pandas.DataFrame(((c.security_id, c.trade_date.year, c.capital_gain, c.acb_total)
                               for c in CostBasis.objects.get_capgains_table(self.user)))

        pt = df.pivot_table(index=0, columns=1, values=2, aggfunc=sum, fill_value=0,
                            dropna=True, margins=True, margins_name='Total')
        pt.insert(0, 'Cost Basis', df.groupby(0).last()[3])
        pt.insert(1, 'Market Value', pandas.Series(dict(self.GetHoldingDetails().taxable().today_security_values())))
        pt.insert(2, 'Unrealized Gain/Loss', pt['Market Value'] - pt['Cost Basis'])
        pt.loc['Total'] = pt.sum(skipna=True)
        pt.insert(3, 'Gain Percentage', pt['Unrealized Gain/Loss'].divide(pt['Market Value']))
        pt.fillna(0, inplace=True)

        return pt

    def GetInceptionDate(self):
        return self.GetActivities().earliest().trade_date

    def GetRebalanceInfo(self, cashadd=0):
        holdings = self.GetHoldingDetails().today().select_related('account', 'security')
        total_value = sum(h.value for h in holdings) + cashadd
        allocs = self.user.allocations.all().order_by('-desired_pct').prefetch_related('securities')
        for alloc in allocs:
            alloc.fill_allocation(cashadd,
                                  sum(h.value for h in holdings if h.security in alloc.securities.all()),
                                  total_value)

        return allocs

    def get_growth_data(self):
        """
        returns a tuple lists of portfolio value data (days, values, deposits, growth)
        days: a list of days that correspond to the other lists
        values: portfolio values on that date
        deposits: total $ deposited to date
        growth: total profit to date.
        """
        days, values = list(zip(*self.GetHoldingDetails().total_values()))
        dep_days, dep_amounts = map(list, list(zip(*self.GetActivities().get_all_deposits())))
        next_dep = 0
        deposits = []
        for day in days:
            while dep_days and dep_days[0] == day:
                dep_days.pop(0)
                next_dep += dep_amounts.pop(0)
            else:
                deposits.append(next_dep)

        growth = [val - dep for val, dep in zip(values, deposits)]
        ret_list = (days, values, deposits, growth)
        return ret_list

    def get_book_value_by_account_security(self, date):
        book_values = self.GetActivities().before(date).get_total_cad_by_group(('account', 'security'))
        return book_values.exclude(security=None)
