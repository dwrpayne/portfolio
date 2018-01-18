import datetime
from decimal import Decimal
from itertools import groupby
from django.core.exceptions import ValidationError

import pendulum
from django.conf import settings
from django.db import models, transaction, connection
from django.db.models import F, Sum
from django.db.models.functions import ExtractYear
from django.utils.functional import cached_property
from model_utils import Choices
from polymorphic.manager import PolymorphicManager
from polymorphic.models import PolymorphicModel
from polymorphic.query import PolymorphicQuerySet
from polymorphic.showfields import ShowFieldTypeAndContent

import utils.dates
from securities.models import Security, SecurityPriceDetail, SecurityPriceQuerySet
from utils.db import DayMixinQuerySet, SecurityMixinQuerySet
from utils.db import RunningSum
from utils.misc import plotly_iframe_from_url
from utils.misc import xirr, total_return
from .services import GeneratePortfolioPlots


class BaseAccountQuerySet(PolymorphicQuerySet):
    def for_user(self, user):
        return self.filter(user=user) if user else self

    def get_balance_totals(self):
        properties = ['cur_balance', 'cur_cash_balance', 'yesterday_balance', 'today_balance_change']
        return {p: sum(getattr(a, p) for a in self) for p in properties}

    def SyncAllBalances(self):
        for account in self:
            account.SyncBalances()

    def SyncAllActivitiesAndRegenerate(self):
        for account in self:
            account.SyncAndRegenerate()


class BaseAccount(ShowFieldTypeAndContent, PolymorphicModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                             on_delete=models.CASCADE, related_name='accounts_for_user')
    type = models.CharField(max_length=100)
    id = models.CharField(max_length=100, primary_key=True)
    taxable = models.BooleanField(default=True)
    display_name = models.CharField(max_length=100, default='')
    creation_date = models.DateField(default='2009-01-01')

    objects = PolymorphicManager.from_queryset(BaseAccountQuerySet)()

    activitySyncDateRange = 30

    class Meta:
        ordering = ['id']

    def __repr__(self):
        return "BaseAccount({},{},{})".format(self.user, self.id, self.type)

    def __str__(self):
        return self.display_name

    @cached_property
    def cur_cash_balance(self):
        query = self.holdingdetail_set.cash().today().total_values()
        if query:
            return query.first()[1]
        return 0

    @cached_property
    def cur_balance(self):
        return self.GetValueToday()

    @cached_property
    def yesterday_balance(self):
        return self.GetValueAtDate(datetime.date.today() - datetime.timedelta(days=1))

    @cached_property
    def today_balance_change(self):
        return self.cur_balance - self.yesterday_balance

    @cached_property
    def sync_from_date(self):
        last_activity = self.activities.newest_date()
        if last_activity:
            return last_activity + datetime.timedelta(days=1)
        return self.creation_date

    def SyncBalances(self):
        pass

    def import_activities(self, csv_file):
        activity_count = self.activities.all().count()

        self.import_from_csv(csv_file)
        if self.activities.all().count() > activity_count:
            self.RegenerateHoldings()

        Security.objects.Sync(False)
        HoldingDetail.Refresh()

    def import_from_csv(self, csv_file):
        """
        Override this to enable transaction uploading from csv.
        Subclasses are expected to parse the csv and create the necessary BaseRawActivity subclasses.
        """
        pass

    def SyncAndRegenerate(self):
        activity_count = self.activities.all().count()

        if self.activitySyncDateRange:
            date_range = utils.dates.day_intervals(self.activitySyncDateRange, self.sync_from_date)
            print('Syncing all activities for {} in {} chunks.'.format(self, len(date_range)))

            for period in date_range:
                self.CreateActivities(period.start, period.end)

        if self.activities.all().count() > activity_count:
            self.RegenerateHoldings()

    def RegenerateActivities(self):
        self.activities.all().delete()
        with transaction.atomic():
            for raw in self.rawactivities.all():
                raw.CreateActivity()
        self.RegenerateHoldings()

    def RegenerateHoldings(self):
        self.holding_set.all().delete()
        for activity in self.activities.all():
            for security, qty_delta in activity.GetHoldingEffects().items():
                self.holding_set.add_effect(self, security, qty_delta, activity.tradeDate)
        self.holding_set.filter(qty=0).delete()

    def CreateActivities(self, start, end):
        """
        Retrieve raw activity data for the specified account and start/end period.
        Store it in the DB as a subclass of BaseRawActivity.
        Return the newly created raw instances.
        """
        return []

    def GetValueAtDate(self, date):
        result = self.holdingdetail_set.at_date(date).total_values().first()
        if result:
            return result[1]
        return 0

    def GetValueToday(self):
        return self.GetValueAtDate(datetime.date.today())


class AccountCsv(models.Model):
    def upload_path(self, filename):
        return 'accountcsv/{}/{}/{}.{}'.format(self.user.username,
                                               self.account.id,
                                               datetime.date.today().isoformat(),
                                               filename.rsplit('.')[-1])

    csvfile = models.FileField(upload_to=upload_path)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    account = models.ForeignKey(BaseAccount, blank=True)

    def find_matching_account(self):
        """
        :return: The account if it was automatched, None otherwise.
        """
        if not hasattr(self, 'account'):
            data = str(self.csvfile.read())
            self.account = sorted(self.user.userprofile.GetAccounts(),
                key=lambda a: data.count(a.id))[-1]
            return self.account
        return None


class HoldingManager(models.Manager):
    def add_effect(self, account, symbol, qty_delta, date):
        previous_qty = 0
        try:
            current_holding = self.get(security_id=symbol, enddate=None)
            if current_holding.startdate == date:
                current_holding.AddQty(qty_delta)
                return
            else:
                current_holding.SetEndsOn(date - datetime.timedelta(days=1))
                previous_qty = current_holding.qty

        except Holding.MultipleObjectsReturned:
            print("HoldingManager.add_effect() returned multiple holdings for query {} {} {}".format(account, symbol, date))
            raise
        except Holding.DoesNotExist:
            pass

        new_qty = previous_qty + qty_delta
        if new_qty:
            print("Creating {} {} {} {}".format(symbol, new_qty, date, None))
            self.create(account=account, security_id=symbol,
                        qty=new_qty, startdate=date, enddate=None)


class HoldingQuerySet(models.query.QuerySet):
    def current(self):
        return self.filter(enddate=None)

    def for_user(self, user):
        return self.filter(account__user=user)


class Holding(models.Model):
    account = models.ForeignKey(BaseAccount, on_delete=models.CASCADE)
    security = models.ForeignKey(Security, on_delete=models.CASCADE, related_name='holdings')
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    startdate = models.DateField()
    enddate = models.DateField(null=True)

    objects = HoldingManager.from_queryset(HoldingQuerySet)()

    class Meta:
        unique_together = ('account', 'security', 'startdate')
        get_latest_by = 'startdate'
        indexes = [
            models.Index(fields=['security_id', 'enddate']),
            models.Index(fields=['enddate']),
        ]

    def __str__(self):
        return "{} {} {}, {} - {}".format(self.account, self.qty, self.security, self.startdate, self.enddate)

    def __repr__(self):
        return "Holding({},{},{},{},{})".format(self.account, self.security, self.qty, self.startdate, self.enddate)

    def AddQty(self, qty_delta):
        self.qty += qty_delta
        if self.qty == 0:
            self.delete()
        else:
            self.save()

    def SetEndsOn(self, date):
        self.enddate = date
        self.save(update_fields=['enddate'])


class BaseRawActivityQuerySet(PolymorphicQuerySet):
    def create(self, **kwargs):
        with transaction.atomic():
            obj = super().create(**kwargs)
            obj.CreateActivity()
            return obj


class BaseRawActivity(ShowFieldTypeAndContent, PolymorphicModel):
    account = models.ForeignKey(BaseAccount, on_delete=models.CASCADE, related_name='rawactivities')

    objects = BaseRawActivityQuerySet.as_manager()

    def CreateActivity(self):
        pass


class ManualRawActivity(BaseRawActivity):
    day = models.DateField()
    symbol = models.CharField(max_length=100, blank=True, default='')
    description = models.CharField(max_length=1000, blank=True, default='')
    currency = models.CharField(max_length=100, blank=True, null=True)
    qty = models.DecimalField(max_digits=16, decimal_places=6, default=0)
    price = models.DecimalField(max_digits=16, decimal_places=6, default=0)
    netAmount = models.DecimalField(max_digits=16, decimal_places=2)
    type = models.CharField(max_length=100)

    class Meta:
        verbose_name_plural = 'Base Raw Activities'

    @classmethod
    def CreateDeposit(cls, account, day, amount, currency='CAD'):
        ManualRawActivity.objects.create(account=account, day=day, currency=currency,
                                         description='', symbol='', qty=0, price=0,
                                         netAmount=amount, type='Deposit')

    @classmethod
    def CreateFX(cls, account, day, to_currency, from_currency, cad_amt, rate):
        if to_currency == from_currency:
            return
        if to_currency == 'CAD':
            to_amt = cad_amt
            from_amt = cad_amt / rate
        else:
            to_amt = cad_amt / rate
            from_amt = cad_amt
        ManualRawActivity.objects.create(account=account, day=day, qty=0, price=0,
                                         description='AUTO CONV @ {}'.format(rate), symbol='',
                                         currency=from_currency, netAmount=-from_amt, type='FX')
        ManualRawActivity.objects.create(account=account, day=day, qty=0, price=0,
                                         description='AUTO CONV @ {}'.format(rate), symbol='',
                                         currency=to_currency, netAmount=to_amt, type='FX')

    @classmethod
    def CreateBuy(cls, account, day, symbol, price, qty, amount, currency, exch=1, amt_in_cad=True, description=''):
        cls.CreateFX(account, day, currency, 'CAD', amount, exch)

        ManualRawActivity.objects.create(account=account, day=day, qty=qty, price=price,
                                         description=description, symbol=symbol, currency=currency,
                                         netAmount=-amount/exch, type='Buy')

    @classmethod
    def CreateSell(cls, account, day, symbol, price, qty, amount, currency, exch=1, description=''):
        if exch:
            cls.CreateFX(account, day, 'CAD', currency, amount, exch)

        ManualRawActivity.objects.create(account=account, day=day, qty=-qty, price=price,
                                         description=description, symbol='', currency=currency,
                                         netAmount=abs(amount/exch), type='Sell')

    @classmethod
    def CreateDividend(cls, account, day, symbol, amount, tax=0, currency='CAD', exch=1):
        ManualRawActivity.objects.create(account=account, day=day, currency=currency,
                                         description='', symbol=symbol, qty=0, price=0,
                                         netAmount=amount/exch, type='Dividend')
        if tax:
            ManualRawActivity.objects.create(account=account, day=day, currency=currency,
                                         description='Withholding Tax', symbol=symbol, qty=0, price=0,
                                         netAmount=-tax/exch, type='Tax')
        cls.CreateFX(account, day, 'CAD', currency, amount-tax, exch)

    @classmethod
    def CreateFee(cls, account, day, amount, currency='CAD', desc=''):
        ManualRawActivity.objects.create(account=account, day=day, currency=currency,
                                         description=desc, symbol='', qty=0, price=0,
                                         netAmount=-abs(amount), type='Fee')

    def CreateActivity(self):
        security = None
        if self.symbol:
            security, _ = Security.objects.get_or_create(symbol=self.symbol,
                                                         defaults={'currency': self.currency})

        commission = 0
        if self.type in [Activity.Type.Buy, Activity.Type.Sell]:
            commission = self.qty * self.price + self.netAmount

        Activity.objects.create(account=self.account, tradeDate=self.day, security=security,
                                description=self.description, cash_id=self.currency, qty=self.qty,
                                price=self.price, netAmount=self.netAmount,
                                commission=commission, type=self.type, raw=self)


class ActivityManager(models.Manager):
    def create(self, **kwargs):
        if 'cash_id' in kwargs and not kwargs['cash_id']:
            kwargs['cash_id'] = None

        # These types don't affect cash balance.
        if kwargs['type'] in [Activity.Type.Expiry, Activity.Type.Journal]:
            kwargs['cash_id'] = None

        return super().create(**kwargs)

    def create_with_deposit(self, **kwargs):
        self.create(**kwargs)

        kwargs.update({'security' : None, 'description' : 'Generated Deposit', 'qty' : 0,
                      'price' : 0, 'type' : Activity.Type.Deposit})
        kwargs['netAmount'] *= -1
        self.create(**kwargs)

    def create_fx(self, to_currency, to_amount, from_currency, from_amount, **kwargs):
        from_args = kwargs
        from_args['cash_id'] = from_currency
        from_args['netAmount'] = from_amount
        from_args['type'] = Activity.Type.FX
        self.create(**from_args)

        to = kwargs
        to['cash_id'] = to_currency
        to['netAmount'] = to_amount
        to['type'] = Activity.Type.FX
        self.create(**to)


class ActivityQuerySet(models.query.QuerySet, SecurityMixinQuerySet, DayMixinQuerySet):
    day_field = 'tradeDate'

    def taxable(self):
        return self.filter(account__taxable=True)

    def for_user(self, user):
        return self.filter(account__user=user)

    def security_list(self):
        return self.order_by().values_list('security_id', flat=True).distinct()

    def deposits(self):
        return self.filter(type__in=[Activity.Type.Deposit, Activity.Type.Withdrawal])

    def dividends(self):
        return self.filter(type=Activity.Type.Dividend)

    def without_dividends(self):
        return self.exclude(type=Activity.Type.Dividend)

    def get_all_deposits(self, running_totals=False):
        """
        :return: a list of (date, amt, total) tuples
        """
        if not self:
            return []
        if running_totals:
            return self.deposits().annotate(
                cum_total = RunningSum('netAmount', 'tradeDate')
            ).values_list('tradeDate', 'cum_total')
        else:
            return self.deposits().values_list('tradeDate', 'netAmount')

    def newest_date(self):
        """
        :return: The date of the most recent activity.
        """
        try:
            return self.latest().tradeDate
        except self.model.DoesNotExist:
            return None

    def with_cadprices(self):
        """
        Annotates each member of the QuerySet with a "cadprice" field.
        """
        return self.filter(
            tradeDate=F('security__pricedetails__day')).annotate(
            cadprice=Sum(F('security__pricedetails__cadprice'))
        )

    def with_capgains_data(self):
        """
        Annotations as follows.
        capgain: The capital gain (or loss) for this activity specifically.
        acbchange: The change in total ACB from the previous activity.
        totalacb: The total ACB of this security after this activity.
        totalqty: The total quantity of shares held after this activity.
        acbpershare: The average per-share ACB after this activity.
        :return: A list of activities, each annotated with the above additional attributes.
        """
        totalqty = Decimal(0)
        totalacb = Decimal(0)
        acbpershare = Decimal(0)
        activities = list(self.with_cadprices())
        for act in activities:
            if act.qty < 0:
                act.capgain = act.qty * (acbpershare - act.cadprice) + act.commission
                act.acbchange = act.qty * acbpershare
            else:
                act.capgain = 0
                act.acbchange = act.qty * act.cadprice - act.commission

            act.totalqty = totalqty = totalqty + act.qty
            act.totalacb = totalacb = max(0, totalacb + act.acbchange)
            act.acbpershare = acbpershare = totalacb / totalqty if totalqty else 0
        return activities


class Activity(models.Model):
    account = models.ForeignKey(BaseAccount, on_delete=models.CASCADE, related_name='activities')
    tradeDate = models.DateField()
    security = models.ForeignKey(Security, on_delete=models.CASCADE,
                                 null=True, related_name='activities')
    description = models.CharField(max_length=1000)
    cash = models.ForeignKey(Security, on_delete=models.CASCADE,
                             null=True, related_name='dontaccess_cash')
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    netAmount = models.DecimalField(max_digits=16, decimal_places=2)
    commission = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    Type = Choices('Deposit', 'Dividend', 'FX', 'Fee', 'Interest', 'Buy', 'Sell', 'Tax',
                   'Transfer', 'Withdrawal', 'Expiry', 'Journal', 'RetCapital', 'NotImplemented')
    type = models.CharField(max_length=100, choices=Type)
    raw = models.ForeignKey(BaseRawActivity, on_delete=models.CASCADE)

    objects = ActivityManager.from_queryset(ActivityQuerySet)()

    class Meta:
        unique_together = ('raw', 'type', 'cash')
        verbose_name_plural = 'Activities'
        get_latest_by = 'tradeDate'
        ordering = ['tradeDate']

    def __str__(self):
        return "{} - {} - {}\t{}\t{}\t{}\t{}".format(self.account, self.tradeDate, self.security, self.qty, self.price,
                                                     self.type, self.description)

    def __repr__(self):
        return "Activity({},{},{},{},{},{},{},{})".format(self.tradeDate, self.security_id, self.cash_id, self.qty,
                                                          self.price, self.netAmount, self.type, self.description)

    def clean(self):
        if self.security is None:
            if not self.type in [self.Type.Deposit, self.Type.Fee, self.Type.FX,
                                 self.Type.Interest, self.Type.Withdrawal]:
                raise ValidationError


    def GetHoldingEffects(self):
        """
        Returns a map from symbol to amount for each security that is affected by this activity.
        """
        effects = {}
        if self.cash:
            effects[self.cash.symbol] = self.netAmount
        if self.security and self.type != Activity.Type.Dividend:
            effects[self.security.symbol] = self.qty
        return effects


class AllocationQuerySet(models.QuerySet):
    def with_current_info(self):
        return self.filter(securities__holdingdetails__account__user=F('user'),
                    securities__holdingdetails__day=datetime.date.today()).annotate(
                    current_amt=Sum('securities__holdingdetails__value'))

    def with_rebalance_info(self, total_value, cashadd):
        allocs = self.with_current_info()

        for alloc in allocs:
            if alloc.securities.filter(symbol='CAD').exists():
                alloc.current_amt += cashadd

            alloc.current_pct = alloc.current_amt / total_value
            alloc.desired_amt = alloc.desired_pct * total_value
            alloc.buysell = alloc.desired_amt - alloc.current_amt
        return allocs


class Allocation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE, related_name='allocations')
    securities = models.ManyToManyField(Security)
    desired_pct = models.DecimalField(max_digits=6, decimal_places=4)

    objects = AllocationQuerySet.as_manager()

    def __str__(self):
        return "{} - {} - {}".format(self.user, self.desired_pct, self.list_securities)

    def __repr__(self):
        return "Allocation<{},{},{}>".format(self.user, self.desired_pct, self.list_securities)

    @property
    def list_securities(self):
        if any(s.symbol == 'CAD' for s in self.securities.all()):
            return 'Cash'
        return ', '.join([s.symbol for s in self.securities.all()])


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    plotly_url = models.CharField(max_length=500, null=True, blank=True)
    plotly_url2 = models.CharField(max_length=500, null=True, blank=True)
    phone = models.CharField(max_length=32, null=True, blank=True)
    country = models.CharField(max_length=32, null=True, blank=True)

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

    def GetCapgainsByYear(self):
        activities_all = self.GetActivities(only_taxable=True)
        securities = self.GetCapGainsSecurities()
        all_years = list(range(self.GetInceptionDate().year, datetime.date.today().year+1))
        yearly_data = {s : [0]*len(all_years) for s in securities}
        year_offset = all_years[0]
        last_acb = {}

        for security in securities:
            activities = activities_all.filter(security_id=security).without_dividends().with_capgains_data()
            for year, yearly_activities in groupby(activities, lambda a: a.tradeDate.year):
                for a in yearly_activities:
                    yearly_data[a.security_id][year-year_offset] += a.capgain
                    last_acb[a.security_id] = a.totalacb

        pending_gains = {}
        for security, value in self.GetHoldingDetails().taxable().today_security_values():
            if security in last_acb:
                pending_gains[security] = value - last_acb[security]

        return all_years, yearly_data, pending_gains

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


class HoldingDetailQuerySet(SecurityPriceQuerySet):
    def __str__(self):
        return '\n'.join(str(h) for h in self)

    def for_user(self, user):
        return self.filter(account__user=user)

    def taxable(self):
        return self.filter(account__taxable=True)

    def cash(self):
        return self.filter(type=Security.Type.Cash)

    def week_end(self):
        return self.order_by('day').filter(day__in=utils.dates.week_ends(self.earliest().day))

    def month_end(self):
        return self.order_by('day').filter(day__in=utils.dates.month_ends(self.earliest().day))

    def year_end(self):
        return self.order_by('day').filter(day__in=utils.dates.year_ends(self.earliest().day))

    def account_values(self):
        return self.order_by('day').values_list('account', 'day').annotate(total=Sum('value'))

    def total_values(self):
        return self.order_by('day').values_list('day').annotate(Sum('value'))

    def today_security_values(self):
        return self.today().order_by('security_id').values_list('security_id').annotate(total=Sum('value'))

    def today_account_values(self):
        return self.today().account_values().values_list('account', 'total')

    def yesterday_account_values(self):
        return self.yesterday().account_values().values_list('account', 'total')


class HoldingDetail(models.Model):
    account = models.ForeignKey(BaseAccount, on_delete=models.DO_NOTHING)
    security = models.ForeignKey(Security, on_delete=models.DO_NOTHING, related_name='holdingdetails')
    day = models.DateField()
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    exch = models.DecimalField(max_digits=16, decimal_places=6)
    cad = models.DecimalField(max_digits=16, decimal_places=6)
    value = models.DecimalField(max_digits=16, decimal_places=6)
    type = models.CharField(max_length=100)

    objects = HoldingDetailQuerySet.as_manager()

    @classmethod
    def CreateView(cls):
        SecurityPriceDetail.CreateView(drop_cascading=True)
        cursor = connection.cursor()
        try:
            cursor.execute("""
DROP MATERIALIZED VIEW IF EXISTS financeview_holdingdetail;

CREATE MATERIALIZED VIEW financeview_holdingdetail
TABLESPACE pg_default
AS
 SELECT h.account_id,
    h.security_id,
    p.day,
    h.qty,
    p.price,
    p.exch,
    p.cadprice AS cad,
    p.cadprice * h.qty AS value,
    row_number() OVER () AS id,
    p.type
   FROM finance_holding h
     JOIN securities_cadview p ON h.security_id::text = p.security_id::text AND h.startdate <= p.day AND (p.day <= h.enddate OR h.enddate IS NULL)
WITH DATA;

ALTER TABLE financeview_holdingdetail OWNER TO financeuser;""")
            connection.commit()
        finally:
            cursor.close()

    @classmethod
    def Refresh(cls):
        SecurityPriceDetail.Refresh()
        cursor = connection.cursor()
        try:
            cursor.execute("REFRESH MATERIALIZED VIEW financeview_holdingdetail;")
            connection.commit()
        finally:
            cursor.close()

    class Meta:
        managed = False
        db_table = 'financeview_holdingdetail'
        get_latest_by = 'day'
        ordering = ['day', 'security']

    def __str__(self):
        return '{} {} {} {:.2f} {:.2f} {:.4f} {:.2f} {:.2f}'.format(
            self.account_id, self.day, self.security_id, self.qty,
            self.price, self.exch, self.cad, self.value)

    def __repr__(self):
        return '{} {} {} {:.2f} {:.2f} {:.4f} {:.2f} {:.2f}'.format(
            self.account_id, self.day, self.security_id, self.qty,
            self.price, self.exch, self.cad, self.value)

    def __radd__(self, other):
        if other == 0:
            return HoldingChange.create_from_detail(self)
        raise NotImplementedError()

    def __add__(self, other):
        return HoldingChange.create_from_detail(self) + HoldingChange.create_from_detail(other)

    def __rsub__(self, other):
        return HoldingChange.create_delta(self, other)

    def __sub__(self, other):
        if not other:
            price = SecurityPriceDetail.objects.get(security_id=self.security_id, day=self.day - datetime.timedelta(days=1))
            return HoldingChange.delta_from_price(price, self)
        return HoldingChange.create_delta(other, self)


class HoldingChange:
    def __init__(self, account=None, security=None, qty=Decimal(0), value=Decimal(0),
                 price=Decimal(0), day=None, exch=Decimal(1)):
        self.account = account
        self.security = security
        self.day = day
        self.qty = qty
        self.qty_delta = 0
        self.value = value
        self.value_delta = 0
        self.value_percent_delta = 0
        self.price = price
        self.price_delta = 0
        self.price_percent_delta = 0
        self.exch = exch

    @staticmethod
    def create_from_detail(detail):
        assert isinstance(detail, HoldingDetail)

        hc = HoldingChange(account=detail.account, security=detail.security, qty=detail.qty,
                           value=detail.value, price=detail.price, day=detail.day, exch=detail.exch
                           )
        return hc

    @staticmethod
    def delta_from_price(price, holding):
        hc = HoldingChange(account=holding.account, security=holding.security,
                           qty=holding.qty, value=holding.value, price=holding.price,
                           day=holding.day, exch=holding.exch)
        hc.day_from = price.day
        hc.price_delta = holding.price - holding.price
        hc.price_percent_delta = hc.price_delta / price.price
        hc.value_delta = holding.value
        hc.value_percent_delta = 0
        hc.qty_delta = holding.qty
        return hc

    @staticmethod
    def create_delta(previous, current):
        if not current:
            current = HoldingChange(account=previous.account, security=previous.security,
                                    price=previous.price, exch=previous.exch,
                                    day=previous.day + datetime.timedelta(days=1))
        if not previous:
            previous = HoldingChange(account=current.account, security=current.security,
                                     price=current.price, exch=current.exch,
                                     day=current.day - datetime.timedelta(days=1))

        assert previous.account == current.account
        assert previous.security == current.security
        assert previous.day < current.day

        hc = HoldingChange(account=current.account, security=current.security,
                           qty=current.qty, value=current.value, price=current.price,
                           day=current.day, exch=current.exch)
        hc.day_from = previous.day
        hc.price_delta = current.price - previous.price
        hc.price_percent_delta = hc.price_delta / previous.price
        hc.value_delta = current.value - previous.value
        hc.value_percent_delta = hc.value_delta / previous.value
        hc.qty_delta = current.qty - previous.qty
        return hc

    def __str__(self):
        return "{} {} {}({}) {} {} {}".format(self.security, self.price,
                                              self.price_delta, self.value_percent_delta,
                                               self.qty, self.value, self.value_delta)

    def __repr__(self):
        return "{} {} {}({}) {} {} {}".format(self.security, self.price,
                                              self.price_delta, self.value_percent_delta,
                                               self.qty, self.value, self.value_delta)

    @property
    def security_type(self):
        return self.security.type

    def __radd__(self, other):
        if other == 0:
            return self
        raise NotImplementedError()

    def __add__(self, other):
        if isinstance(other, HoldingDetail):
            other = HoldingChange.create_from_detail(other)
        assert isinstance(other, HoldingChange)
        assert self.day == other.day

        ret = HoldingChange(day=self.day, value=self.value + other.value)

        if self.account == other.account:
            ret.account = self.account

        if self.security == other.security:
            ret.security = self.security
            ret.qty = self.qty + other.qty
            ret.qty_delta = self.qty_delta + other.qty_delta
            ret.price = self.price
            ret.price_delta = self.price_delta
            ret.price_percent_delta = ret.price_delta / (ret.price - ret.price_delta)

        ret.value_delta = self.value_delta + other.value_delta
        ret.value_percent_delta = ret.value_delta / (ret.value - ret.value_delta)

        return ret
