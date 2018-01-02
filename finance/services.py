import plotly
import plotly.graph_objs as go

from utils.misc import find_le_index
import datetime


class LineGraph:
    def __init__(self, graph_name_unique):
        self.traces = []
        self.filename = graph_name_unique
        self.url = None

    @property
    def is_plotted(self):
        return not self.url

    def add_trace(self, name, tuples, mode='lines+markers'):
        self.add_trace_xy(name, *list(zip(*tuples)), mode)

    def add_trace_xy(self, name, x_values, y_values, mode='lines+markers'):
        self.traces.append(go.Scattergl(name=name, x=x_values, y=y_values, mode=mode))

    def plot(self):
        self.url = plotly.plotly.plot(self.traces, filename=self.filename, auto_open=False)
        return self.url


def GenerateSecurityPlot(security):
    graph = LineGraph('security-values-{}'.format(security.symbol))
    graph.add_trace('Price (CAD)', security.pricedetails.values_list('day', 'cadprice'))
    return graph.plot()


def GenerateReturnPlot(userprofile):
    graph = LineGraph('returns-{}'.format(userprofile.username))
    graph.add_trace('MROR%', userprofile.PeriodicRatesOfReturn())
    graph.add_trace('YROR%', userprofile.PeriodicRatesOfReturn('years'))
    return graph.plot()


def GeneratePortfolioPlots(userprofile):
    graph = LineGraph('portfolio-values-short-{}'.format(userprofile.username))
    day_val_pairs = userprofile.GetHoldingDetails().total_values()
    graph.add_trace('Total', day_val_pairs)

    deposits = userprofile.GetActivities().get_all_deposits(running_totals=True)
    dep_dates, dep_totals = list(zip(*deposits))
    dep_dates = dep_dates + (datetime.date.today(),)
    dep_totals = dep_totals + (dep_totals[-1],)
    graph.add_trace_xy('Deposits', x_values=dep_dates, y_values=dep_totals)

    growth = [(day, val - dep_totals[find_le_index(dep_dates, day, 0)]) for day, val in day_val_pairs]
    graph.add_trace('Growth', growth)
    plot1 = graph.plot()

    graph = LineGraph('portfolio-growth-short-{}'.format(userprofile.username))
    daily_growth = []
    for (y_day, y_val), (t_day, t_val) in zip(growth, growth[1:]):
        if abs(t_val - y_val) > 1:
            daily_growth.append((t_day, t_val - y_val))
    graph.add_trace('Daily growth', daily_growth, mode='markers')
    plot2 = graph.plot()

    return plot1, plot2

    # dep_dict = dict(deposits)
    # sp = Security.objects.get(symbol='SPXTR')
    # sp_prices_byday = dict(sp.prices.filter(
    #    day=F('security__currency__rates__day')
    #    ).values_list(
    #        'day', F('price') * F('security__currency__rates__price')
    #    ))
    # sp_qtys = {}
    # deps = dict(deposits)    # running_qty = 0
    # for day, dep in deps.items():
    #    running_qty += dep / sp_prices_byday[day]
    #    sp_qtys[day]=running_qty

    # sp_vals = {day : sp_qtys[find_le(list(sp_qtys), day, dates[0])] * sp_prices_byday[day] for day in dates}
    # sp_lists = list(zip(*sorted(list(sp_vals.items()))))
    # traces.append( go.Scatter(name='SP 500', x=sp_lists[0], y=sp_lists[1], mode='lines+markers') )
