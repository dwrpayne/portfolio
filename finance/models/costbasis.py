from decimal import Decimal
from itertools import groupby

from django.db import models, transaction
from .activity import Activity

class CostBasisQuerySet(models.QuerySet):
    def for_security(self, security):
        return self.filter(activity__security=security)

    def for_user(self, user):
        return self.filter(activity__account__user=user)


class CostBasisManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related('activity')

    def create_from_activities(self, activity_query):
        for security, activities in groupby(activity_query.with_exchange_rates().order_by('security', 'tradeDate'),
                                            lambda a: a.security_id):
            if security:#with transaction.atomic():
                prev_costbasis = CostBasis()
                for act in activities:
                    prev_costbasis = self.create_with_previous(act, prev_costbasis)

    def create_with_previous(self, activity, previous_costbasis):
        cad_commission = activity.commission * activity.exch
        cad_price = activity.price * activity.exch
        if not cad_price:
            cad_price = activity.security.prices.get(day=activity.tradeDate).price * activity.exch
        total_cad_value = activity.qty * cad_price - cad_commission

        if activity.qty < 0:
            assert previous_costbasis.acb_per_share is not None, "Trying to create a Sell CostBasis with no previous holding!"
            capital_gain = activity.qty * (previous_costbasis.acb_per_share - cad_price) + cad_commission
            acb_change = activity.qty * previous_costbasis.acb_per_share
        else:
            capital_gain = 0
            acb_change = total_cad_value

        qty_total = previous_costbasis.qty_total + activity.qty
        acb_total = max(0, previous_costbasis.acb_total + acb_change)
        acb_per_share = acb_total / qty_total if qty_total else 0

        return super().create(activity=activity, cad_price_per_share=cad_price, total_cad_value=total_cad_value,
                              cad_commission=cad_commission, acb_total=acb_total, acb_change=acb_change,
                              acb_per_share=acb_per_share, qty_total=qty_total, capital_gain=capital_gain)

    def create(self, activity, **kwargs):
        latest_costbasis = self.for_user(activity.account.user).for_security(activity.security).latest('activity__tradeDate')
        return self.create_with_previous(activity, latest_costbasis)


class CostBasis(models.Model):
    """
    CostBasis
    """
    activity = models.OneToOneField(Activity, null=True, blank=True, on_delete=models.CASCADE)
    cad_price_per_share = models.DecimalField(max_digits=16, decimal_places=6)
    total_cad_value = models.DecimalField(max_digits=16, decimal_places=6)
    cad_commission = models.DecimalField(max_digits=16, decimal_places=6)
    acb_total = models.DecimalField(max_digits=16, decimal_places=6, default=0)
    acb_change = models.DecimalField(max_digits=16, decimal_places=6)
    acb_per_share = models.DecimalField(max_digits=16, decimal_places=6)
    qty_total = models.DecimalField(max_digits=16, decimal_places=6, default=0)
    capital_gain = models.DecimalField(max_digits=16, decimal_places=6)

    objects = CostBasisManager.from_queryset(CostBasisQuerySet)()

    class Meta:
        ordering = ['activity__tradeDate']

