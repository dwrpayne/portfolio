from django.conf import settings
from django.db import models
from django.db.models import Sum

from itertools import chain
from securities.models import Security


class Allocation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE, related_name='allocations')
    securities = models.ManyToManyField(Security)
    desired_pct = models.DecimalField(max_digits=6, decimal_places=4)


    def __str__(self):
        return "{} - {} - {}".format(self.user, self.desired_pct, self.list_securities)

    def __repr__(self):
        return "Allocation<{},{},{}>".format(self.user, self.desired_pct, self.list_securities)

    @property
    def list_securities(self):
        if any(s.symbol == 'CAD' for s in self.securities.all()):
            return 'Cash'
        return ', '.join([s.symbol for s in self.securities.all()])

