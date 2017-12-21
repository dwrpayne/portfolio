import datetime
import requests
from django.conf import settings
from django.db import models, transaction, connection
from django.db.models import Sum
from django.utils.functional import cached_property
from model_utils import Choices
from polymorphic.manager import PolymorphicManager
from polymorphic.models import PolymorphicModel
from polymorphic.query import PolymorphicQuerySet
from polymorphic.showfields import ShowFieldTypeAndContent

import utils.dates
from utils.misc import plotly_iframe_from_url
from securities.models import Security, SecurityPriceDetail

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


class BaseAccountManager(PolymorphicManager):
    def SyncAllBalances(self):
        for account in self.get_queryset():
                account.SyncBalances()

    def SyncActivitiesAndRegenerate(self, user):
        for account in self.for_user(user):
                account.SyncAndRegenerate()

class BaseAccount(ShowFieldTypeAndContent, PolymorphicModel):
    client = models.ForeignKey(BaseClient, on_delete=models.CASCADE, related_name='accounts')
    type = models.CharField(max_length=100)
    id = models.CharField(max_length=100, primary_key=True)
    taxable = models.BooleanField(default=True)
    display_name = models.CharField(max_length=100, editable=False, default='')
    creation_date = models.DateField(default='2009-01-01')

    objects = BaseAccountManager.from_queryset(BaseAccountQuerySet)()

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
            for security, qty_delta in activity.GetHoldingEffects():
                self.holding_set.add_effect(self, security, qty_delta, activity.tradeDate)
        self.holding_set.filter(qty=0).delete()

    def GetValueAtDate(self, date):
        return self.holdingdetail_set.at_date(date).total_values().first()[1]

    def GetValueToday(self):
        return self.holdingdetail_set.today().total_values().first()[1]


class HoldingManager(models.Manager):
    def add_effect(self, account, security, qty_delta, date):
        previous_qty = 0
        try:
            current_holding = self.get(security=security, enddate=None)
            if current_holding.startdate == date:
                current_holding.AddQty(qty_delta)
                return
            else:
                current_holding.SetEndsOn(date - datetime.timedelta(days=1))
                previous_qty = current_holding.qty

        except Holding.MultipleObjectsReturned:
            print("HoldingManager.add_effect() returned multiple holdings for query {} {} {}".format(account, security, date))
        except Holding.DoesNotExist:
            pass

        new_qty = previous_qty + qty_delta
        if new_qty:
            print("Creating {} {} {} {}".format(security, new_qty, date, None))
            self.create(account=account, security=security,
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
                                commission = commission, type=self.type, raw=self)


class ActivityManager(models.Manager):
    def create(self, *args, **kwargs):
        if 'cash_id' in kwargs and not kwargs['cash_id']:
            kwargs['cash_id'] = None

        # These types don't affect cash balance.
        if kwargs['type'] in [Activity.Type.Expiry, Activity.Type.Journal]:
            kwargs['cash_id'] = None

        return super().create(*args, **kwargs)

    def newest_date(self):
        try:
            return self.get_queryset().latest().tradeDate
        except self.model.DoesNotExist:
            return None

    def create_with_deposit(self, *args, **kwargs):
        self.create(*args, **kwargs)

        kwargs.update({'security' : None, 'description' : 'Generated Deposit', 'qty' : 0,
                      'price' : 0, 'type' : Activity.Type.Deposit})
        kwargs['netAmount'] *= -1
        self.create(*args, **kwargs)


class ActivityQuerySet(models.query.QuerySet):
    def in_year(self, year):
        return self.filter(tradeDate__year=year)

    def taxable(self):
        return self.filter(account__taxable=True)

    def for_user(self, user):
        return self.filter(account__client__user=user)

    def deposits(self):
        return self.filter(type=Activity.Type.Deposit)

    def dividends(self):
        return self.filter(type=Activity.Type.Dividend)

    def without_dividends(self):
        return self.exclude(type=Activity.Type.Dividend)


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
        """Yields a (security, amount) for each security that is affected by this activity."""
        if self.cash:
            yield self.cash, self.netAmount

        if self.security and self.type != Activity.Type.Dividend:
            yield self.security, self.qty

        return


class Allocation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE, related_name='allocations')
    securities = models.ManyToManyField(Security)
    desired_pct = models.DecimalField(max_digits=6, decimal_places=4)

    def __str__(self):
        return "{} - {} - {}".format(self.user, self.desired_pct, self.list_securities())

    def __repr__(self):
        return "Allocation<{},{},{}>".format(self.user, self.desired_pct, self.list_securities())

    def list_securities(self):
        return ', '.join([s.symbol for s in self.securities.all()])


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    plotly_url = models.CharField(max_length=500, null=True, blank=True)

    def GetHeldSecurities(self):
        return Holding.objects.for_user(self.user
                                        ).current().values_list('security_id', flat=True).distinct()

    def GetTaxableSecurities(self):
        return Holding.objects.filter(
            account__taxable=True
        ).exclude(security__type=Security.Type.Cash
                  ).for_user(self.user).current().values_list('security_id', flat=True).distinct()

    def GetAccounts(self):
        return BaseAccount.objects.filter(client__user=self.user)

    @property
    def portfolio_iframe(self):
        return plotly_iframe_from_url(self.plotly_url)


class HoldingDetailQuerySet(models.query.QuerySet):
    def for_user(self, user):
        return self.filter(account__client__user=user)

    def at_date(self, date):
        return self.filter(day=date)

    def date_range(self, startdate, enddate):
        return self.filter(day__range=(startdate, enddate))

    def today(self):
        return self.at_date(datetime.date.today())

    def yesterday(self):
        return self.at_date(datetime.date.today() - datetime.timedelta(days=1))

    def cash(self):
        return self.filter(type=Security.Type.Cash)

    def week_end(self):
        return self.filter(day__in=utils.dates.week_ends(self.earliest().day))

    def month_end(self):
        return self.filter(day__in=utils.dates.month_ends(self.earliest().day))

    def year_end(self):
        return self.filter(day__in=utils.dates.year_ends(self.earliest().day))

    def account_values(self):
        return self.values_list('account', 'day').annotate(Sum('value'))

    def total_values(self):
        return self.values_list('day').annotate(Sum('value'))

    def by_security(self, by_account=False):
        columns = ['security', 'day']
        if by_account:
            columns.insert(1, 'account')
        return self.values(*columns, 'price', 'exch', 'cad',
                           ).annotate(total_qty=Sum('qty'), total_val=Sum('value')
                                      ).order_by(*columns)


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
        ordering = ['day']

    def __str__(self):
        return '{} {} {} {:.2f} {:.2f} {:.4f} {:.2f} {:.2f}'.format(
            self.account_id, self.day, self.security_id, self.qty,
            self.price, self.exch, self.cad, self.value)

    def __repr__(self):
        return '{} {} {} {:.2f} {:.2f} {:.4f} {:.2f} {:.2f}'.format(
            self.account_id, self.day, self.security_id, self.qty,
            self.price, self.exch, self.cad, self.value)
