from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, RowRange, Sum, Window
from django.utils.functional import cached_property
from model_utils import Choices
from polymorphic.models import PolymorphicModel
from polymorphic.query import PolymorphicQuerySet
from polymorphic.showfields import ShowFieldTypeAndContent
from itertools import groupby

from securities.models import Security, SecurityPriceDetail
from utils.db import DayMixinQuerySet, SecurityMixinQuerySet
from .account import BaseAccount


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
    net_amount = models.DecimalField(max_digits=16, decimal_places=2)
    type = models.CharField(max_length=100)

    class Meta:
        verbose_name_plural = 'Base Raw Activities'

    @classmethod
    def CreateDeposit(cls, account, day, amount, currency='CAD'):
        ManualRawActivity.objects.create(account=account, day=day, currency=currency,
                                         description='', symbol='', qty=0, price=0,
                                         net_amount=amount, type='Deposit')

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
                                         currency=from_currency, net_amount=-from_amt, type='FX')
        ManualRawActivity.objects.create(account=account, day=day, qty=0, price=0,
                                         description='AUTO CONV @ {}'.format(rate), symbol='',
                                         currency=to_currency, net_amount=to_amt, type='FX')

    @classmethod
    def CreateBuy(cls, account, day, symbol, price, qty, amount, currency, exch=1, amt_in_cad=True, description=''):
        cls.CreateFX(account, day, currency, 'CAD', amount, exch)

        ManualRawActivity.objects.create(account=account, day=day, qty=qty, price=price,
                                         description=description, symbol=symbol, currency=currency,
                                         net_amount=-amount / exch, type='Buy')

    @classmethod
    def CreateSell(cls, account, day, symbol, price, qty, amount, currency, exch=1, description=''):
        if exch:
            cls.CreateFX(account, day, 'CAD', currency, amount, exch)

        ManualRawActivity.objects.create(account=account, day=day, qty=-qty, price=price,
                                         description=description, symbol=symbol, currency=currency,
                                         net_amount=abs(amount / exch), type='Sell')

    @classmethod
    def CreateDividend(cls, account, day, symbol, amount, tax=0, currency='CAD', exch=1):
        ManualRawActivity.objects.create(account=account, day=day, currency=currency,
                                         description='', symbol=symbol, qty=0, price=0,
                                         net_amount=amount / exch, type='Dividend')
        if tax:
            ManualRawActivity.objects.create(account=account, day=day, currency=currency,
                                             description='Withholding Tax', symbol=symbol, qty=0, price=0,
                                             net_amount=-tax / exch, type='Tax')
        cls.CreateFX(account, day, 'CAD', currency, amount - tax, exch)

    @classmethod
    def CreateFee(cls, account, day, amount, currency='CAD', desc=''):
        ManualRawActivity.objects.create(account=account, day=day, currency=currency,
                                         description=desc, symbol='', qty=0, price=0,
                                         net_amount=-abs(amount), type='Fee')

    def CreateActivity(self):
        security = None
        if self.symbol:
            self.symbol = self.symbol.rsplit('.', 1)[0]
            security, _ = Security.objects.get_or_create(symbol=self.symbol,
                                                         defaults={'currency': self.currency})

        commission = 0
        if self.type in [Activity.Type.Buy, Activity.Type.Sell]:
            commission = self.qty * self.price + self.net_amount

        Activity.objects.create(account=self.account, trade_date=self.day, security=security,
                                description=self.description, cash_id=self.currency, qty=self.qty,
                                price=self.price, net_amount=self.net_amount,
                                commission=commission, type=self.type, raw=self)


class ActivityManager(models.Manager):
    def create(self, **kwargs):
        if 'cash_id' in kwargs and not kwargs['cash_id']:
            kwargs['cash_id'] = None

        if kwargs['type'] == Activity.Type.Dividend:
            kwargs['qty'] = 0

        return super().create(**kwargs)

    def create_with_deposit(self, **kwargs):
        self.create(**kwargs)

        kwargs.update({'security': None, 'description': 'Generated Deposit', 'qty': 0,
                       'price': 0, 'type': Activity.Type.Deposit})
        kwargs['net_amount'] *= -1
        self.create(**kwargs)

    def create_with_withdrawal(self, **kwargs):
        self.create(**kwargs)

        kwargs.update({'security': None, 'description': 'Generated Withdrawal', 'qty': 0,
                       'price': 0, 'type': Activity.Type.Withdrawal})
        kwargs['net_amount'] *= -1
        self.create(**kwargs)

    def create_fx(self, to_currency, to_amount, from_currency, from_amount, **kwargs):
        from_args = kwargs
        from_args['cash_id'] = from_currency
        from_args['net_amount'] = from_amount
        from_args['type'] = Activity.Type.FX
        self.create(**from_args)

        to = kwargs
        to['cash_id'] = to_currency
        to['net_amount'] = to_amount
        to['type'] = Activity.Type.FX
        self.create(**to)


class ActivityQuerySet(models.query.QuerySet, SecurityMixinQuerySet, DayMixinQuerySet):
    day_field = 'trade_date'

    def taxable(self):
        return self.filter(account__taxable=True)

    def for_user(self, user):
        return self.filter(account__user=user)

    def security_list(self):
        return self.order_by().values_list('security_id', flat=True).distinct()

    def deposits(self):
        return self.filter(type__in=[Activity.Type.Deposit,
                                     Activity.Type.Withdrawal,
                                     Activity.Type.Transfer])

    def transactions(self):
        return self.exclude(security=None).exclude(qty=0)

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
                cum_total=Window(
                    expression=Sum('net_amount'),
                    order_by=F('trade_date').asc(),
                    frame=RowRange(end=0)
                )
            ).values_list('trade_date', 'cum_total')
        else:
            return self.deposits().values_list('trade_date', F('net_amount') * F('account__joint_share'))

    def newest_date(self):
        """
        :return: The date of the most recent activity.
        """
        try:
            return self.latest().trade_date
        except self.model.DoesNotExist:
            return None

    def with_exchange_rates(self):
        """
        Annotates each activity of the QuerySet with a "exch" field.
        """
        return self.filter(
            trade_date=F('cash__prices__day')).annotate(
            exch=Sum(F('cash__prices__price'))
        )

    def get_total_cad_by_group(self, columns):
        return self.order_by().filter(trade_date=F('cash__prices__day')).annotate(
            net_amount_cad=F('net_amount') * F('cash__prices__price')
        ).annotate(_total_cad=Sum('net_amount_cad')).values(
            *columns, '_total_cad'
        ).annotate(total_cad=F('_total_cad')).values_list(*columns, 'total_cad')


class Activity(models.Model):
    account = models.ForeignKey(BaseAccount, on_delete=models.CASCADE, related_name='activities')
    trade_date = models.DateField()
    security = models.ForeignKey(Security, on_delete=models.CASCADE,
                                 blank=True, null=True, related_name='activities')
    description = models.CharField(max_length=1000)
    cash = models.ForeignKey(Security, on_delete=models.CASCADE,
                             blank=True, null=True, related_name='dontaccess_cash')
    qty = models.DecimalField(max_digits=16, decimal_places=6)
    price = models.DecimalField(max_digits=16, decimal_places=6)
    net_amount = models.DecimalField(max_digits=16, decimal_places=2)
    commission = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    Type = Choices('Deposit', 'Dividend', 'FX', 'Fee', 'Interest', 'Buy', 'Sell', 'Tax',
                   'Transfer', 'Withdrawal', 'Expiry', 'Journal', 'RetCapital', 'NotImplemented')
    type = models.CharField(max_length=100, choices=Type)
    raw = models.ForeignKey(BaseRawActivity, on_delete=models.CASCADE)

    objects = ActivityManager.from_queryset(ActivityQuerySet)()

    class Meta:
        unique_together = ('raw', 'type', 'cash')
        verbose_name_plural = 'Activities'
        get_latest_by = 'trade_date'
        ordering = ['trade_date']

    def __str__(self):
        return "{} - {} - {}\t{}\t{}\t{}\t{}".format(self.account, self.trade_date, self.security, self.qty, self.price,
                                                     self.type, self.description)

    def __repr__(self):
        return "Activity({},{},{},{},{},{},{},{})".format(self.trade_date, self.security_id, self.cash_id, self.qty,
                                                          self.price, self.net_amount, self.type, self.description)

    def clean(self):
        if self.security is None:
            if not self.type in [self.Type.Deposit, self.Type.Fee, self.Type.FX,
                                 self.Type.Interest, self.Type.Withdrawal]:
                raise ValidationError

    @cached_property
    def cad_price(self):
        return SecurityPriceDetail.objects.get(security=self.security_id, day=self.trade_date).price

    def GetHoldingEffects(self):
        """
        Returns a map from symbol to amount for each security that is affected by this activity.
        """
        effects = {}
        if self.cash:
            effects[self.cash.symbol] = self.net_amount
        if self.security and self.type != Activity.Type.Dividend:
            effects[self.security.symbol] = self.qty
        return effects


class CostBasisManager(models.Manager):
    def _finalize(self, queryset, separate_by_account=False):
        """
        Creates CostBasis objects from a QuerySet of Activities. Internal only.
        :param queryset: An Activity QuerySet.
        :param separate_by_account: Calculate each account's Cost Basis separately.
        :return: A QuerySet of CostBasis models.
        """
        groupby_fn = lambda a: a.security_id
        if separate_by_account:
            queryset = queryset.order_by('security', 'account', 'trade_date')
            groupby_fn = lambda a: (a.account_id, a.security_id)

        for security, activities in groupby(queryset, groupby_fn):
            if security:
                prev_costbasis = CostBasis.create_null()
                for act in activities:
                    act.post_initialize(prev_costbasis)
                    prev_costbasis = act
        queryset.model = self.model
        return queryset

    def create(self, **kwargs):
        assert False, "Don't create a CostBasis!"

    def get_queryset(self):
        return super().get_queryset().transactions().with_exchange_rates().exclude(type=Activity.Type.Transfer)

    def get_activities_with_acb(self, user, security):
        """
        Retrieves a QuerySet of filled out CostBasis models for a single security in this user's taxable accounts.
        """
        return list(self._finalize(self.get_queryset().for_user(user).taxable().for_security(security)))

    def get_capgains_table(self, user):
        """
        Retrieves a QuerySet of filled out CostBasis models for this users taxable accounts.
        """
        return self._finalize(self.get_queryset().for_user(user).taxable())


class CostBasis(Activity):
    """
    A proxy model of Activity with the following extra fields. Create them from an
    Activity QuerySet across all taxable accounts.
    This model only makes sense when created using the manager utility functions.

    exch: Exchange rate to CAD on the trade_date.
    cad_commission: Commission, in CAD.
    cad_price_per_share: Price per share in this transaction, in CAD.
    qty_total: Total # of shares held of this security, post-transaction.
    total_cad_value: Total value of all shares held, post-transaction, in CAD.
    acb_total: Total ACB of this security, post-transaction, in CAD.
    acb_per_share: ACB per share, post-transaction, in CAD.
    capital_gain: Total unrealized capital gain of this security, post-transaction, in CAD.
    acb_change: The effect this transaction had on the total ACB, in CAD.
    """
    objects = CostBasisManager.from_queryset(ActivityQuerySet)()

    class Meta:
        ordering = ['security', 'trade_date', '-qty']
        get_latest_by = 'trade_date'
        proxy = True

    def __str__(self):
        return "On {}, {} shares of {}, book value {:.2f}".format(self.trade_date, self.qty_total, self.security_id, self.acb_total)

    def __repr__(self):
        return "CostBasis<{},{},{},{:.2f}".format(self.trade_date, self.qty_total, self.security_id, self.acb_total)

    @classmethod
    def create_null(cls):
        basis = cls()
        basis.qty_total = 0
        basis.acb_per_share = 0
        basis.acb_total = 0
        return basis

    def post_initialize(self, previous_costbasis):
        self.cad_commission = self.commission * self.exch
        if not self.price:
            self.price = self.security.prices.get(day=self.trade_date).price
        self.cad_price_per_share = self.price * self.exch
        self.total_cad_value = self.qty * self.cad_price_per_share - self.cad_commission

        is_buying = self.qty > 0
        is_selling = self.qty < 0
        is_long = previous_costbasis.qty_total > 0
        is_short = previous_costbasis.qty_total < 0

        if (is_short and is_buying) or (is_long and is_selling):
            self.capital_gain = self.qty * (previous_costbasis.acb_per_share - self.cad_price_per_share) + self.cad_commission
            self.acb_change = self.qty * previous_costbasis.acb_per_share
        else:
            self.capital_gain = 0
            self.acb_change = self.total_cad_value

        self.qty_total = previous_costbasis.qty_total + self.qty
        self.acb_total = max(0, previous_costbasis.acb_total + self.acb_change)
        self.acb_per_share = self.acb_total / self.qty_total if self.qty_total else 0
