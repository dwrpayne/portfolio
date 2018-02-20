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
        self.highchart.set_options('title', {'text':title})

    def xaxis(self, title):
        self.highchart.set_options('xAxis', {'title': {'enabled':True, 'text':title}})
        return self

    def yaxis(self, title):
        self.highchart.set_options('yAxis', {'title': {'enabled':True, 'text':title}})
        return self

    def datetime(self):
        self.highchart.set_options('xAxis', {'type': 'datetime'})
        return self

    def boost_gpu(self):
        self.highchart.set_options('boost', {'useGPUTranslations': True})
        return self

    def bold_zero_axis(self):
        self.highchart.set_options('yAxis', {'plotLines': [{'value':0, 'width':2, 'color':'black'}]})
        return self

    def navigator(self, enabled=True):
        self.highchart.set_options('navigator', {'enabled': enabled})
        return self

    def zoom(self, zoomtype):
        self.highchart.set_options('chart', {'zoomType': zoomtype})
        return self

    def tooltipvalues(self, prefix='', suffix='', decimals=2):
        self.highchart.set_options('plotOptions', {'series': {'tooltip': {'valueDecimals': decimals,
                                                                          'valuePrefix': prefix,
                                                                          'valueSuffix': suffix}}})
        return self

    def shared_tooltip(self):
        self.highchart.set_options('tooltip', {'split':False, 'shared':True})
        return self

    def set_option(self, **kwargs):
        self.highchart.set_options(**kwargs)

    def add_trace(self, name, data, series_type='line', **kwargs):
        self.highchart.add_data_set(list(data), name=name, series_type=series_type, **kwargs)
        #pass

    def add_csv(self, csv_file):
        self.csv_file = csv_file

    def plot(self):
        self.highchart.buildcontent()
        return self.highchart._htmlcontent.decode('utf-8')


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


def get_portfolio_graphs(userprofile):
    graph = HighChartLineGraph('Portfolio Value Over Time'.format(userprofile.username))
    graph.datetime().boost_gpu().bold_zero_axis().navigator(False).zoom('xy').tooltipvalues(prefix='$', decimals=2).shared_tooltip()

    day_val_pairs = userprofile.GetHoldingDetails().total_values()
    if not day_val_pairs:
        return None, None
    value_data = [(datetime.combine(day, datetime.min.time()), int(val)) for day, val in day_val_pairs]

    deposits = list(userprofile.GetActivities().get_all_deposits(running_totals=True))
    deposits.append((date.today(), deposits[-1][1]))
    deposits_data = [(datetime.combine(day, datetime.min.time()), int(value)) for day, value in deposits]

    dep_dates, dep_totals = list(zip(*deposits))
    prev_dates = [d - timedelta(days=1) for d in dep_dates[1:]] + [date.today()]
    dep_dates = list(chain.from_iterable(zip(dep_dates, prev_dates)))
    dep_totals = list(chain.from_iterable(zip(dep_totals, dep_totals)))
    growth = [(datetime.combine(day, datetime.min.time()), int(val - dep_totals[find_le_index(dep_dates, day, 0)])) for day, val in day_val_pairs]

    graph.add_trace('Total Value', value_data, color='blue')
    graph.add_trace('Total Contributions', deposits_data, step='left', color='orange')
    graph.add_trace('Net Growth', growth, color='lime', negativeColor='red')

    plot1 = graph.plot()

    graph = HighChartLineGraph('Daily Gain/Loss')
    graph.datetime().boost_gpu().navigator(False).zoom('xy').tooltipvalues(decimals=2).shared_tooltip()
    graph.highchart.add_JSsource('https://code.highcharts.com/stock/indicators/indicators.js')
    daily_growth = []
    for (y_day, y_val), (t_day, t_val) in window(growth):
        daily_growth.append((t_day, t_val - y_val))

    graph.add_trace('Daily growth', [], series_type='scatter', id='growth',
                    color='royalblue', marker={'radius':2, 'symbol':'circle'},
                    tooltip={'headerFormat':'<span style="font-size: 10px">{point.key}</span><br/>',
                             'pointFormatter': '''function() {
                                                   if (this.y >=0) {
                                                        return "Gain: <b>$" + this.y + "</b>";
                                                   }
                                                   return "Loss: <b>$(" + Math.abs(this.y) + ")</b>";
                                               }'''})

    period = 60
    graph.add_trace('{} Day Average Daily Profit'.format(period), [], series_type='line',
                    linkedTo='growth', params={'period':period},
                    color='lime', negativeColor='red',
                    tooltip={'pointFormat': '<span style="color:{point.color}">\u25CF</span> {series.name}: <b>${point.y:.2f}</b><br/>'})
    plot2 = graph.plot()

    return plot1, plot2
