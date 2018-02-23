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

