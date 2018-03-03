import datetime
from decimal import Decimal

from django.db import models, connection
from django.db.models import Sum

import utils.dates
from securities.models import Security, SecurityPriceDetail, SecurityPriceQuerySet
from .account import BaseAccount


class HoldingManager(models.Manager):
    def add_effect(self, account, symbol, qty_delta, date):
        # Hack david's joint accounts to be half.
        if account.pk in [18,19,20,21,22,23,24,25] and date < datetime.date(2018,1,19):
            qty_delta /= 1#2

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
    enddate = models.DateField(null=True, blank=True)

    objects = HoldingManager.from_queryset(HoldingQuerySet)()

    class Meta:
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
        return self.order_by('day').values_list('account__display_name', 'day').annotate(total=Sum('value'))

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
