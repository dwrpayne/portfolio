from datetime import date, datetime, timedelta
from itertools import chain
from django.db.models import Sum
from utils.misc import find_le_index, window

from highcharts import Highstock


class RefreshButtonHandlerMixin:
    """
    Mixin to add support for my custom refresh button.
    """
    def get(self, request, *args, **kwargs):
        if request.is_ajax():
            key = next(key for key in request.GET if key.startswith('refresh-'))
            _, action = key.split('-',1)
            return self.ajax_request(request, action)
        return super().get(request, *args, **kwargs)

    def ajax_request(self, request, action):
        pass


def get_growth_data(userprofile):
    days, values = list(zip(*userprofile.GetHoldingDetails().total_values()))
    dep_days, dep_amounts = map(list, list(zip(*userprofile.GetActivities().get_all_deposits())))
    next_dep = 0
    deposits = []
    for day in days:
        while dep_days and dep_days[0] == day:
            dep_days.pop(0)
            next_dep += dep_amounts.pop(0)
        else:
            deposits.append(next_dep)

    growth = [val - dep for val, dep in zip(values, deposits)]
    return days, values, deposits, growth

