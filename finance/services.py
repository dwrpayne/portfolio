from itertools import accumulate

import plotly
import plotly.graph_objs as go
from django.db.models import Sum

from utils.misc import find_le_index
from .models import Activity, HoldingDetail


def GetRebalanceInfo(user):
    holdings = HoldingDetail.objects.for_user(user).today().by_security()
    total_value = sum(h['total_val'] for h in holdings)

    allocs = user.allocations.all()
    for alloc in allocs:
        alloc.current_amt = holdings.filter(
            security__in=alloc.securities.all()).aggregate(
            total=Sum('total_val'))['total']
        alloc.current_pct = alloc.current_amt / total_value
        alloc.desired_amt = alloc.desired_pct * total_value
        alloc.buysell = alloc.desired_amt - alloc.current_amt

    missing = holdings.exclude(security__in=allocs.values_list('securities'))
    for h in missing:
        h['current_pct'] = h['total_val'] / total_value

    return allocs, missing


def GenerateSecurityPlot(security):
    pairs = [(r.day, r.cadprice) for r in security.rates.with_cad_prices()]
    dates, vals = list(zip(*pairs))

    filename = 'security-values-{}'.format(security.symbol)

    plotly_url = plotly.plotly.plot(
        [go.Scatter(name='Price (CAD)', x=dates, y=vals, mode='lines+markers')],
        filename=filename, auto_open=False)

    return plotly_url


def GeneratePlot(user):
    traces = []

    pairs = HoldingDetail.objects.for_user(user).week_end().total_values()
    dates, vals = list(zip(*pairs))
    traces.append(go.Scatter(name='Total', x=dates, y=vals, mode='lines+markers'))

    deposits = Activity.objects.for_user(user).deposits().values_list('tradeDate', 'netAmount')
    deposit_dates, amounts = list(zip(*list(deposits)))
    running_deposits = list(accumulate(amounts))
    traces.append(go.Scatter(name='Deposits', x=deposit_dates, y=running_deposits, mode='lines+markers'))

    # dep_dict = dict(deposits)
    # sp = Security.objects.get(symbol='SPXTR')
    # sp_prices_byday = dict(sp.rates.filter(
    #    day=F('security__currency__rates__day')
    #    ).values_list(
    #        'day', F('price') * F('security__currency__rates__price')
    #    ))
    # sp_qtys = {}
    # deps = dict(deposits)
    # running_qty = 0
    # for day, dep in deps.items():
    #    running_qty += dep / sp_prices_byday[day]
    #    sp_qtys[day]=running_qty

    # sp_vals = {day : sp_qtys[find_le(list(sp_qtys), day, dates[0])] * sp_prices_byday[day] for day in dates}
    # sp_lists = list(zip(*sorted(list(sp_vals.items()))))
    # traces.append( go.Scatter(name='SP 500', x=sp_lists[0], y=sp_lists[1], mode='lines+markers') )

    growth_vals = [val - sum(amounts[0:find_le_index(deposit_dates, date, 0) + 1]) for date, val in pairs]
    traces.append(go.Scatter(name='Growth', x=dates, y=growth_vals, mode='lines+markers'))

    plotly_url = plotly.plotly.plot(
        traces, filename='portfolio-values-short-{}'.format(user.username), auto_open=False)
    user.userprofile.plotly_url = plotly_url
    user.userprofile.save()
