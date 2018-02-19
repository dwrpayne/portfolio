from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, RowRange, Sum, Window
from django.utils.functional import cached_property
from model_utils import Choices
from polymorphic.models import PolymorphicModel
from polymorphic.query import PolymorphicQuerySet
from polymorphic.showfields import ShowFieldTypeAndContent

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

        if kwargs['type'] == Activity.Type.Dividend:
            kwargs['qty'] = 0

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
        return self.filter(type__in=[Activity.Type.Deposit,
                                     Activity.Type.Withdrawal,
                                     Activity.Type.Transfer])

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
                cum_total = Window(
                    expression=Sum('netAmount'),
                    order_by=F('tradeDate').asc(),
                    frame=RowRange(end=0)
                )
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
            cad_price=Sum(F('security__pricedetails__cadprice'))
        )


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

    @cached_property
    def cad_price(self):
        return SecurityPriceDetail.objects.get(security=self.security_id, day=self.tradeDate).price

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
