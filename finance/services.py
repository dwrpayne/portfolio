from django.db import models

from .models import Security, Holding, Activity, HoldingDetail

from itertools import accumulate
from bisect import bisect_right
import plotly
import plotly.graph_objs as go
from utils.misc import find_le

def GetRebalanceInfo(user):
    securities = Security.objects.with_prices(user)
    total_value = sum(s.value for s in securities)

    allocs = list(user.allocations.all().prefetch_related('securities'))
    for alloc in allocs:
        alloc.current_amt = sum(s.value for s in securities if s in alloc.securities.all())
        alloc.current_pct = alloc.current_amt / total_value
        alloc.desired_amt = alloc.desired_pct * total_value
        alloc.buysell = alloc.desired_amt - alloc.current_amt
    allocs.sort(key=lambda a: a.desired_pct, reverse=True)

    missing = [s for s in securities if not s.allocation_set.exists()]
    for s in missing:
        s.current_pct = s.value / total_value

    return allocs, missing


def GeneratePlot(user):
    pairs = HoldingDetail.objects.for_user(user).month_end().total_values().ordered()
    dates, vals = list(zip(*pairs))
    trace = go.Scatter(name='Total', x=dates, y=vals, mode='lines+markers')
    
    deposits = Activity.objects.for_user(user).deposits().values_list('tradeDate', 'netAmount')
    deposit_dates, amounts = list(zip(*list(deposits)))
    running_deposits=list(accumulate(amounts))
    trace2 = go.Scatter(name='Deposits', x=deposit_dates, y=running_deposits, mode='lines+markers')

    growth_vals = [val - running_deposits[max(0,bisect_right(deposit_dates, date)-1)] for date,val in pairs]
    trace3 = go.Scatter(name='Growth', x=dates, y=growth_vals, mode='lines+markers')

    plotly_url = plotly.plotly.plot(
        [trace, trace2, trace3], filename='portfolio-values-short-{}'.format(user.username), auto_open=False)
    user.userprofile.plotly_url = plotly_url
    user.userprofile.save()

def GetAccountValueHistory(user, period):
    return HoldingDetail.objects.for_user(user).month_end().account_values().ordered()

def GetTotalValueHistory(user, period):
    return HoldingDetail.objects.for_user(user).month_end().total_values().ordered()