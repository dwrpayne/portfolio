from django.conf import settings
from django.db import models

from securities.models import Security


class AllocationManager(models.Manager):
    def for_user(self, user):
        return self.get_queryset().filter(user=user)

    def get_unallocated_securities(self, user=None):
        if not user:
            user = self.instance
        allocated = self.for_user(user).values_list('securities', flat=True).exclude(
            securities__symbol=None)
        held = user.userprofile.GetHeldSecurities().exclude(symbol__in=allocated)
        return held

    def ensure_allocated(self, security, user):
        allocs = Allocation.objects.filter(securities=security)
        #if not allocs:
        #    self.reallocate_security(security, user=user)

    def reallocate_security(self, security, sourceid=None, targetid=None, user=None):
        """
        Removes the security from source if it exists there.
        Add the security to target if target exists.
        Otherwise, create a new Allocation and add the security to it.
        :param security: The security (or symbol) to move
        :param source: The id of the source allocation.
        :param target: The id of the target allocation.
        :param user: The user under which to create the allocation, if target is None.
        :return: The source and target allocations.
        """
        try:
            source = Allocation.objects.get(pk=sourceid)
            source.securities.remove(security)
        except Allocation.DoesNotExist:
            source = None

        target, created = self.get_or_create(pk=targetid, defaults={'user': user})
        target.securities.add(security)
        return source, target


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

    def fill_allocation(self, cashadd, holding_value, total_value):
        self.current_amt = holding_value
        if any(s.symbol == 'CAD' for s in self.securities.all()):
            self.current_amt += cashadd
        self.current_pct = self.current_amt / total_value * 100
        self.desired_amt = self.desired_pct * total_value / 100
        self.buysell = self.desired_amt - self.current_amt
