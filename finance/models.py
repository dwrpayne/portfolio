import datetime
import pendulum
import copy
from decimal import Decimal
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
from utils.db import RunningSum
from utils.misc import xirr, total_return
from securities.models import Security, SecurityPriceDetail, SecurityPriceQuerySet
from utils.db import DayMixinQuerySet, SecurityMixinQuerySet
from utils.misc import plotly_iframe_from_url


class BaseClient(ShowFieldTypeAndContent, PolymorphicModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE, related_name='clients')
    display_name = models.CharField(max_length=100, null=True)

    def __str__(self):
        return "{}".format(self.display_name)

    def __repr__(self):
        return 'BaseClient<{}>'.format(self.display_name)

    def __enter__(self):
        self.Authorize()
        return self

    def __exit__(self, type, value, traceback):
        self.CloseSession()

    def Authorize(self):
        pass

    def CloseSession(self):
        pass

    def SyncAccounts(self):
        pass

    def CreateRawActivities(self, account, start, end):
        """
        Retrieve raw activity data from your client source for the specified account and start/end period.
        Store it in the DB as a subclass of BaseRawActivity.
        Return the number of new raw activities created.
        """
        return 0


class BaseAccountQuerySet(PolymorphicQuerySet):
    def for_user(self, user):
        return self.filter(client__user=user) if user else self

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
    client = models.ForeignKey(BaseClient, on_delete=models.CASCADE, related_name='accounts')
    type = models.CharField(max_length=100)
    id = models.CharField(max_length=100, primary_key=True)
    taxable = models.BooleanField(default=True)
    display_name = models.CharField(max_length=100, editable=False, default='')
    creation_date = models.DateField(default='2009-01-01')

    objects = PolymorphicManager.from_queryset(BaseAccountQuerySet)()

    class Meta:
        ordering = ['id']

    def __repr__(self):
        return "BaseAccount({},{},{})".format(self.client, self.id, self.type)

    def __str__(self):
        return "{} {} {}".format(self.client, self.id, self.type)

    def save(self, *args, **kwargs):
        self.display_name = "{} {}".format(self.client, self.type)
        super().save(*args, **kwargs)

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

    @property
    def activitySyncDateRange(self):
        return 30

    @cached_property
    def sync_from_date(self):
        last_activity = self.activities.newest_date()
        if last_activity:
            return last_activity + datetime.timedelta(days=1)
        return self.creation_date

    def SyncBalances(self):
        pass

    def SyncAndRegenerate(self):
        """
        Syncs all raw activities for the specified account from our associated client.
        Returns the number of new raw activities created.
        """
        date_range = utils.dates.day_intervals(self.activitySyncDateRange, self.sync_from_date)

        print('Syncing all activities for {} in {} chunks.'.format(self, len(date_range)))
        with self.client as c:
            new_count = sum(c.CreateRawActivities(self, start, end) for start, end in date_range)
        # TODO: Better error handling when we can't actually sync new activities from server.
        # Should we still regenerate here?
        if new_count >= 0:
            self._RegenerateActivities()
            self._RegenerateHoldings()

    def _RegenerateActivities(self):
        self.activities.all().delete()
        with transaction.atomic():
            for raw in self.rawactivities.all():
                raw.CreateActivity()

    def _RegenerateHoldings(self):
        self.holding_set.all().delete()
        for activity in self.activities.all():
            for security, qty_delta in activity.GetHoldingEffects().items():
                self.holding_set.add_effect(self, security, qty_delta, activity.tradeDate)
        self.holding_set.filter(qty=0).delete()

    def GetValueAtDate(self, date):
        return self.holdingdetail_set.at_date(date).total_values().first()[1]

    def GetValueToday(self):
        return self.holdingdetail_set.today().total_values().first()[1]


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
        return self.filter(account__client__user=user)


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


class BaseRawActivity(ShowFieldTypeAndContent, PolymorphicModel):
    account = models.ForeignKey(BaseAccount, on_delete=models.CASCADE, related_name='rawactivities')

    def CreateActivity(self):
        pass


class ManualRawActivity(BaseRawActivity):
    day = models.DateField()
    symbol = models.CharField(max_length=100)
    description = models.CharField(max_length=1000)
    currency = models.CharField(max_length=100)
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    netAmount = models.DecimalField(max_digits=16, decimal_places=2)
    type = models.CharField(max_length=100)

    class Meta:
        verbose_name_plural = 'Base Raw Activities'

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


class ActivityQuerySet(models.query.QuerySet, SecurityMixinQuerySet, DayMixinQuerySet):
    day_field = 'tradeDate'

    def taxable(self):
        return self.filter(account__taxable=True)

    def for_user(self, user):
        return self.filter(account__client__user=user)

    def deposits(self):
        return self.filter(type__in=[Activity.Type.Deposit, Activity.Type.Transfer])

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
    Type = Choices('Deposit', 'Dividend', 'FX', 'Fee', 'Interest', 'Buy', 'Sell',
                   'Transfer', 'Withdrawal', 'Expiry', 'Journal', 'NotImplemented')
    type = models.CharField(max_length=100, choices=Type)
    raw = models.ForeignKey(BaseRawActivity, on_delete=models.CASCADE)

    objects = ActivityManager.from_queryset(ActivityQuerySet)()

    class Meta:
        unique_together = ('raw', 'type')
        verbose_name_plural = 'Activities'
        get_latest_by = 'tradeDate'
        ordering = ['tradeDate']

    def __str__(self):
        return "{} - {} - {}\t{}\t{}\t{}\t{}".format(self.account, self.tradeDate, self.security, self.qty, self.price,
                                                     self.type, self.description)

    def __repr__(self):
        return "Activity({},{},{},{},{},{},{},{})".format(self.tradeDate, self.security, self.cash, self.qty,
                                                          self.price, self.netAmount, self.type, self.description)

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


class AllocationManager(models.Manager):
    def with_rebalance_info(self, holdings, cashadd):
        total_value = sum(holdings).value + cashadd

        allocs = self.get_queryset()
        for alloc in allocs:
            alloc.update_rebalance_info(cashadd)

        return allocs


class Allocation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE, related_name='allocations')
    securities = models.ManyToManyField(Security)
    desired_pct = models.DecimalField(max_digits=6, decimal_places=4)
    objects = AllocationManager()

    def __str__(self):
        return "{} - {} - {}".format(self.user, self.desired_pct, self.list_securities())

    def __repr__(self):
        return "Allocation<{},{},{}>".format(self.user, self.desired_pct, self.list_securities())

    def list_securities(self):
        return ', '.join([s.symbol for s in self.securities.all()])

    def update_rebalance_info(self, cashadd=0):
        holdings = self.user.userprofile.GetHoldingDetails().today()
        total_value = sum(holdings).value + cashadd
        self.current_amt = sum(holdings.for_securities(self.securities.all())).value
        if self.securities.filter(type=Security.Type.Cash).exists():
            self.current_amt += cashadd

        self.current_pct = self.current_amt / total_value
        self.desired_amt = self.desired_pct * total_value
        self.buysell = self.desired_amt - self.current_amt


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    plotly_url = models.CharField(max_length=500, null=True, blank=True)
    plotly_url2 = models.CharField(max_length=500, null=True, blank=True)

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

    def GetHeldSecurities(self):
        return Holding.objects.for_user(
            self.user).current().values_list('security_id', flat=True).distinct()

    def GetTaxableSecurities(self):
        return Holding.objects.filter(
            account__taxable=True
        ).exclude(security__type=Security.Type.Cash
                  ).for_user(self.user).current().values_list('security_id', flat=True).distinct()

    def GetHoldingDetails(self):
        return HoldingDetail.objects.for_user(self.user)

    def GetAccounts(self):
        return BaseAccount.objects.for_user(self.user)

    def GetAccount(self, account_id):
        return self.GetAccounts().get(id=account_id)

    def GetActivities(self):
        return Activity.objects.for_user(self.user)

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
        """
        :param time_period: Can be 'months', 'years'.
        :return:
        """
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

    def GetInceptionDate(self):
        return self.GetActivities().earliest().tradeDate

    def GetRebalanceInfo(self, cashadd=0):
        holdings = self.GetHoldingDetails().today()
        allocs = self.user.allocations.with_rebalance_info(holdings, cashadd)

        missing = holdings.exclude(security__in=allocs.values_list('securities'))
        total_value = sum(holdings).value + cashadd
        for h in missing:
            h['current_pct'] = h['total_val'] / total_value

        return allocs, missing


class HoldingDetailQuerySet(SecurityPriceQuerySet):
    def for_user(self, user):
        return self.filter(account__client__user=user)

    def cash(self):
        return self.filter(type=Security.Type.Cash)

    def week_end(self):
        return self.order_by('day').filter(day__in=utils.dates.week_ends(self.earliest().day))

    def month_end(self):
        return self.order_by('day').filter(day__in=utils.dates.month_ends(self.earliest().day))

    def year_end(self):
        return self.order_by('day').filter(day__in=utils.dates.year_ends(self.earliest().day))

    def account_values(self):
        return self.values_list('account', 'day').annotate(Sum('value'))

    def total_values(self):
        return self.order_by('day').values_list('day').annotate(Sum('value'))


class HoldingDetail(models.Model):
    account = models.ForeignKey(BaseAccount, on_delete=models.DO_NOTHING)
    security = models.ForeignKey(Security, on_delete=models.DO_NOTHING)
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

    def __sub__(self, other):
        return HoldingChange.create_delta(other, self)


class HoldingChange:
    def __init__(self):
        self.account = None
        self.security = None
        self.qty = 0
        self.value = 0
        self.value_delta = 0
        self.price = 0
        self.price_delta = 0
        self.percent_gain = 0

    @staticmethod
    def create_from_detail(detail):
        assert isinstance(detail, HoldingDetail)

        hc = HoldingChange()
        hc.account = detail.account
        hc.security = detail.security
        hc.day = detail.day
        hc.price = detail.price
        hc.exch = detail.exch
        hc.qty = detail.qty
        hc.value = detail.value
        return hc

    @staticmethod
    def create_delta(previous, current):
        assert previous.account_id == current.account_id
        assert previous.security_id == current.security_id
        assert previous.day < current.day

        hc = HoldingChange()
        hc.account = current.account
        hc.security = current.security
        hc.day = current.day
        hc.day_from = previous.day
        hc.price = current.price
        hc.price_delta = current.price - previous.price
        hc.percent_gain = hc.price_delta / previous.price
        hc.exch = current.exch
        hc.qty = current.qty
        hc.value = current.value
        hc.value_delta = current.value - previous.value
        return hc

    def __str__(self):
        return "{} {} {}({}) {} {} {}".format(self.security, self.price, self.price_delta, self.percent_gain,
                                               self.qty, self.value, self.value_delta)

    def __repr__(self):
        return "{} {} {}({}) {} {} {}".format(self.security, self.price, self.price_delta, self.percent_gain,
                                               self.qty, self.value, self.value_delta)

    def __radd__(self, other):
        if other == 0:
            return self
        raise NotImplementedError()

    def __add__(self, other):
        if isinstance(other, HoldingDetail):
            other = HoldingChange.create_from_detail(other)
        assert isinstance(other, HoldingChange)
        assert self.day == other.day

        ret = HoldingChange()

        if self.account == other.account:
            ret.account = self.account

        if self.security == other.security:
            ret.security = self.security
            ret.qty = self.qty + other.qty
            ret.price = self.price
            ret.price_delta = self.price_delta

        ret.day = self.day
        ret.value = self.value + other.value
        ret.value_delta = self.value_delta + other.value_delta
        ret.percent_gain = ret.value_delta / (ret.value - ret.value_delta)

        return ret
