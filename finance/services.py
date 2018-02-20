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


class HighChartLineGraph:
    def __init__(self, title, width=700, height=500):
        self.highchart = Highstock(width=width, height=height)
        self.highchart.set_options('xAxis', {'type': 'datetime', 'minRange': 14 * 24 * 3600000})
        self.highchart.set_options('yAxis', {'plotLines': [{'value':0, 'width':2, 'color':'black'}]})
        self.highchart.options['boost'] = {}
        self.highchart.set_options('boost', {'useGPUTranslations': True}, force_options=True)
        self.highchart.set_options('title', {'text': title})
        self.highchart.set_options('navigator', {'enabled': False})
        self.highchart.set_options('chart', {'zoomType': 'xy'})
        #self.highchart.set_options('rangeSelector', {'floating': True,'y': 0 })
        self.highchart.set_options('plotOptions', {'series': {'tooltip': {'valueDecimals': 2}}})

    def add_trace(self, name, tuples, series_type='line', **kwargs):
        data = list(tuples)
        self.highchart.add_data_set(data, series_type=series_type, name=name, **kwargs)

    def set_titles(self, xaxis='', yaxis='', title=''):
        if xaxis: self.highchart.set_options('xAxis', {'title': {'enabled':True, 'text':xaxis}})
        if yaxis: self.highchart.set_options('yAxis', {'title': {'enabled':True, 'text':yaxis}})

    def plot(self):
        self.highchart.buildcontent()
        return self.highchart.iframe


def GenerateSecurityPlot(security, activities=None):
    def fix_prices(prices):
        return [(datetime.combine(day, datetime.min.time()), float(round(price, 2))) for day, price in prices]

    graph = HighChartLineGraph(security.symbol, width=1000)
    graph.add_trace('Price ({})'.format(security.currency), fix_prices(security.pricedetails.values_list('day', 'price')),
                    id='price')

    #if not security.currency == 'CAD':
    #    graph.add_trace('Price (CAD)', fix_prices(security.pricedetails.values_list('day', 'cadprice')))

    graph.add_trace('Purchases', [{'x': datetime.combine(day, datetime.min.time()),
                                   'fillColor': 'GreenYellow' if qty > 0 else 'red',
                                   'title': str(int(qty)),
                                   'text': '{} {:.0f} @ {:.2f}'.format('Buy' if qty > 0 else 'Sell', qty, price),
                                   } for day, qty, price in activities.transactions().values('tradeDate').annotate(total_qty=Sum('qty')).values_list('tradeDate', 'total_qty', 'price')],
                    series_type='flags', onSeries='price', shape='squarepin')

    graph.add_trace('Dividends', [{'x': datetime.combine(day, datetime.min.time()),
                                   'fillColor': 'LightCyan',
                                   'title': '${:.2f}'.format(price),
                                   'text': 'Dividend of ${:.2f}'.format(price),
                                   } for day, price in activities.dividends().values_list('tradeDate', 'price').distinct()],
                    series_type='flags', shape='circlepin')

    return graph.plot()


def get_portfolio_graphs(userprofile):
    graph = HighChartLineGraph('Portfolio Value Over Time'.format(userprofile.username))
    graph.highchart.set_options('tooltip', {'split':False, 'shared':True})
    day_val_pairs = userprofile.GetHoldingDetails().total_values()
    if not day_val_pairs:
        return None, None
    graph.add_trace('Total Value', [(datetime.combine(day, datetime.min.time()), int(val)) for day, val in day_val_pairs],
                    color='blue', height=600, tooltip={'valuePrefix': '$', 'valueDecimals': 0})

    deposits = list(userprofile.GetActivities().get_all_deposits(running_totals=True))
    deposits.append((date.today(), deposits[-1][1]))
    graph.add_trace('Total Contributions',
                    [(datetime.combine(day, datetime.min.time()), int(value)) for day, value in deposits],
                    step='left', color='orange', tooltip={'valuePrefix':'$', 'valueDecimals': 0})

    dep_dates, dep_totals = list(zip(*deposits))
    prev_dates = [d - timedelta(days=1) for d in dep_dates[1:]] + [date.today()]
    dep_dates = list(chain.from_iterable(zip(dep_dates, prev_dates)))
    dep_totals = list(chain.from_iterable(zip(dep_totals, dep_totals)))
    growth = [(datetime.combine(day, datetime.min.time()), int(val - dep_totals[find_le_index(dep_dates, day, 0)])) for day, val in day_val_pairs]
    graph.add_trace('Net Growth', growth, color='lime', negativeColor='red', tooltip={'valuePrefix':'$', 'valueDecimals': 0})

    plot1 = graph.plot()

    graph = HighChartLineGraph('Daily Gain/Loss')
    graph.highchart.add_JSsource('https://code.highcharts.com/stock/indicators/indicators.js')
    daily_growth = []
    for (y_day, y_val), (t_day, t_val) in window(growth):
        daily_growth.append((t_day, t_val - y_val))

    graph.add_trace('Daily growth', daily_growth, series_type='scatter', id='growth',
                    color='royalblue', marker={'radius':2, 'symbol':'circle'},
                    tooltip={'headerFormat':'<span style="font-size: 10px">{point.key}</span><br/>',
                             'pointFormatter': '''function() {
                                                   if (this.y >=0) {
                                                        return "Gain: <b>$" + this.y + "</b>";
                                                   } 
                                                   return "Loss: <b>$(" + Math.abs(this.y) + ")</b>";
                                               }'''})

    period = 60
    graph.add_trace('{} Day Average Daily Profit'.format(period), [], series_type='sma',
                    linkedTo='growth', params={'period':period},
                    color='lime', negativeColor='red',
                    tooltip={'pointFormat': '<span style="color:{point.color}">\u25CF</span> {series.name}: <b>${point.y:.2f}</b><br/>'})
    plot2 = graph.plot()

    return plot1, plot2
