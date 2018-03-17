from django.conf import settings
from django.db import models

from securities.models import Security


class AllocationManager(models.Manager):
    def get_unallocated_securities(self, user=None):
        if not user:
            user = self.instance
        allocated = self.get_queryset().filter(user=user).values_list('securities', flat=True)
        held = user.userprofile.GetHeldSecurities().exclude(symbol__in=allocated)
        return held

    def move_security(self, security, source, target):
        source_alloc = Allocation.objects.get(pk=source)
        target_alloc = Allocation.objects.get(pk=target)
        if not security in source_alloc.securities.values_list('symbol', flat=True):
            return

        source_alloc.securities.remove(security)
        target_alloc.securities.add(security)


class Allocation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE, related_name='allocations')
    securities = models.ManyToManyField(Security)
    desired_pct = models.DecimalField(max_digits=4, decimal_places=1, default=0)

    objects = AllocationManager()

    def __str__(self):
        return "{} - {} - {}".format(self.user, self.desired_pct, self.list_securities)

    def __repr__(self):
        repr = "Allocation<{},{},{},{},{},{}>".format(self.user, self.list_securities, self.desired_pct,
                                                      round(getattr(self, 'current_pct', 0), 1),
                                                      round(getattr(self, 'desired_amt', 0), 1),
                                                      round(getattr(self, 'current_amt', 0), 1))
        return repr

    @property
    def list_securities(self):
        if any(s.symbol == 'CAD' for s in self.securities.all()):
            return 'Cash'
        return ', '.join([s.symbol for s in self.securities.all()])
