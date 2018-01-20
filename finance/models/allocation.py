import datetime

from django.conf import settings
from django.db import models
from django.db.models import F, Sum

from securities.models import Security


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

