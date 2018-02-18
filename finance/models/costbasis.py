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
        for security, activities in groupby(activity_query.with_cadprices().order_by('security', 'tradeDate'),
                                            lambda a: a.security_id):
            with transaction.atomic():
                qty_total = Decimal(0)
                acb_total = Decimal(0)
                acb_per_share = Decimal(0)
                for act in activities:
                    costbasis = CostBasis(activity=act)
                    if act.qty < 0:
                        costbasis.capital_gain = act.qty * (acb_per_share - act.cad_price) + act.commission
                        costbasis.acb_change = act.qty * acb_per_share
                    else:
                        costbasis.capital_gain = 0
                        costbasis.acb_change = act.qty * act.cad_price - act.commission

                    costbasis.cad_price_per_share = act.cad_price
                    costbasis.qty_total = qty_total = qty_total + act.qty
                    costbasis.acb_total = acb_total = max(0, acb_total + costbasis.acb_change)
                    costbasis.acb_per_share = acb_per_share = acb_total / qty_total if qty_total else 0
                    costbasis.save()

    def create(self, activity, **kwargs):
        latest_costbasis = self.for_user(activity.account.user).for_security(activity.security).latest('activity__tradeDate')
        if activity.qty < 0:
            capital_gain = activity.qty * (latest_costbasis.acbpershare - activity.cad_price) + activity.commission
            acb_change = activity.qty * latest_costbasis.acbpershare
        else:
            capital_gain = 0
            acb_change = activity.qty * activity.cad_price - activity.commission

        qty_total = latest_costbasis.qty_total + activity.qty
        acb_total = max(0, latest_costbasis.acb_total + acb_change)
        acb_per_share = acb_total / qty_total if qty_total else 0

        super().create(activity=activity, acb_total=acb_total, acb_change=acb_change,
                       acb_per_share=acb_per_share, qty_total=qty_total,
                       capital_gain=capital_gain, cad_price_per_share=activity.cad_price)


class CostBasis(models.Model):
    activity = models.OneToOneField(Activity, null=True, blank=True, on_delete=models.CASCADE)
    cad_price_per_share = models.DecimalField(max_digits=16, decimal_places=6)
    acb_total = models.DecimalField(max_digits=16, decimal_places=6)
    acb_change = models.DecimalField(max_digits=16, decimal_places=6)
    acb_per_share = models.DecimalField(max_digits=16, decimal_places=6)
    qty_total = models.DecimalField(max_digits=16, decimal_places=6)
    capital_gain = models.DecimalField(max_digits=16, decimal_places=6)

    objects = CostBasisManager.from_queryset(CostBasisQuerySet)()

    class Meta:
        ordering = ['activity__tradeDate']

