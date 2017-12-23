import datetime
from itertools import accumulate
import pendulum
import plotly
import plotly.graph_objs as go
from django.db.models import Sum
from django.db.models.functions import ExtractYear

from utils.misc import find_le_index
from .models import SecurityPriceDetail

def GenerateSecurityPlot(security):
    pairs = security.pricedetails.values_list('day', 'cadprice')
    dates, vals = list(zip(*pairs))

    filename = 'security-values-{}'.format(security.symbol)

    plotly_url = plotly.plotly.plot(
        [go.Scatter(name='Price (CAD)', x=dates, y=vals, mode='lines+markers')],
        filename=filename, auto_open=False)

    return plotly_url

def GenerateReturnPlot(userprofile):
    traces = []
    start = userprofile.GetInceptionDate()
    


def GeneratePlot(userprofile):
    traces = []

    pairs = userprofile.GetHoldingDetails().week_end().total_values()
    dates, vals = list(zip(*pairs))
    traces.append(go.Scatter(name='Total', x=dates, y=vals, mode='lines+markers'))

    deposit_dates, deposit_amounts, deposit_running_totals = userprofile.GetActivities().get_deposits_with_running_totals()
    traces.append(go.Scatter(name='Deposits', x=deposit_dates, y=deposit_running_totals, mode='lines+markers'))

    # dep_dict = dict(deposits)
    # sp = Security.objects.get(symbol='SPXTR')
    # sp_prices_byday = dict(sp.prices.filter(
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

    growth_vals = [val - sum(deposit_amounts[0:find_le_index(deposit_dates, date, 0) + 1]) for date, val in pairs]
    traces.append(go.Scatter(name='Growth', x=dates, y=growth_vals, mode='lines+markers'))

    plotly_url = plotly.plotly.plot(
        traces, filename='portfolio-values-short-{}'.format(userprofile.username), auto_open=False)
    userprofile.update_plotly_url(plotly_url)

def GetCommissionByYear(userprofile):
    return dict(userprofile.GetActivities().annotate(
        year=ExtractYear('tradeDate')
    ).order_by().values('year').annotate(c=Sum('commission')).values_list('year', 'c'))

def GetLastUserUpdateDay(userprofile):
    last_update_days = SecurityPriceDetail.objects.after(
        datetime.date.today() - datetime.timedelta(days=30)
    ).for_securities(userprofile.GetHeldSecurities()
                     ).order_by('security','-day').distinct('security').values_list('day', flat=True)
