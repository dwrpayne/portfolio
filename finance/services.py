import datetime
from itertools import chain

import plotly
import plotly.graph_objs as go

from utils.misc import find_le_index, window


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


class LineGraph:
    def __init__(self, graph_name_unique):
        self.traces = []
        self.filename = graph_name_unique
        self.url = None
        self.title = ''
        self.xaxis_title = ''
        self.yaxis_title = ''

    @property
    def is_plotted(self):
        return not self.url

    def add_trace(self, name, tuples, mode='lines'):
        self.add_trace_xy(name, *list(zip(*tuples)), mode)

    def add_trace_xy(self, name, x_values, y_values, mode='lines'):
        self.traces.append(go.Scattergl(name=name, x=x_values, y=y_values, mode=mode))

    def set_titles(self, title='', xaxis='', yaxis=''):
        self.title = title
        self.xaxis_title = xaxis
        self.yaxis_title = yaxis

    def plot(self):
        layout = go.Layout(title=self.title, xaxis={'title':self.xaxis_title}, yaxis={'title':self.yaxis_title})
        fig = go.Figure(data=self.traces, layout=layout)
        self.url = plotly.plotly.plot(fig, filename=self.filename, auto_open=False)
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
    if not day_val_pairs:
        return None, None
    graph.add_trace('Total', day_val_pairs)

    deposits = dict(userprofile.GetActivities().get_all_deposits(running_totals=True))
    dep_dates, dep_totals = list(zip(*deposits.items()))
    prev_dates = [d - datetime.timedelta(days=1) for d in dep_dates[1:]] + [datetime.date.today()]
    dep_dates = list(chain.from_iterable(zip(dep_dates, prev_dates)))
    dep_totals = list(chain.from_iterable(zip(dep_totals, dep_totals)))
    graph.add_trace_xy('Deposits', x_values=dep_dates, y_values=dep_totals)

    growth = [(day, val - dep_totals[find_le_index(dep_dates, day, 0)]) for day, val in day_val_pairs]
    graph.add_trace('Total Growth', growth)

    graph.set_titles(title='Portfolio Value Over Time')
    plot1 = graph.plot()

    graph = LineGraph('portfolio-growth-short-{}'.format(userprofile.username))
    daily_growth = []
    for (y_day, y_val), (t_day, t_val) in window(growth):
        daily_growth.append((t_day, t_val - y_val))

    moving_average_size=60
    moving_average = []
    for entries in window(daily_growth, moving_average_size):
        average = sum(val for day, val in entries) / moving_average_size
        moving_average.append((entries[-1][0], average))

    daily_growth = [pair for pair in daily_growth if abs(pair[1])>1]

    graph.add_trace('Daily growth', daily_growth, mode='markers')
    graph.add_trace('{} Day Moving Average'.format(moving_average_size), moving_average, mode='lines')
    graph.set_titles(title='Daily Change in Value')
    plot2 = graph.plot()

    return plot1, plot2
