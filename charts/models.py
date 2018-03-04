from datetime import datetime, time

from django.db.models import Sum


class BaseHighChart:
    container_name = 'container'
    data_param = 'template'
    _is_highchart_model = True
    _JAVASCRIPT_TEMPLATE = '''
    <script>
    $.get("?chart=$data_param", function(data) {
        Highcharts.StockChart()
    });
    </script>
    '''

    def __init__(self, userprofile):
        self.userprofile = userprofile

    def get_javascript(self):
        from string import Template
        s = Template(self._JAVASCRIPT_TEMPLATE)
        return s.safe_substitute({attr: getattr(self, attr) for attr in dir(self) if not callable(attr)})

    def get_data(self, **kwargs):
        return []


class GrowthChart(BaseHighChart):
    container_name = 'growth-div'
    data_param = 'growth'
    _JAVASCRIPT_TEMPLATE = '''
    <script>
    $.get("?chart=$data_param", function(data) {
        Highcharts.StockChart({
            boost: {
                useGPUTranslations: true
            },
            chart: {
                renderTo: "$container_name",
                width: 700,
                height: 500,
                type: 'line',
               zoomType: 'x'
            },
            credits: {
                enabled: false
            },
            data: {
                firstRowAsNames: false,
                rows: data
            },
            legend: {
                enabled: true,
            },
            plotOptions: {
                series: {
                    tooltip: {
                        valueDecimals: 2,
                        valuePrefix: '$'
                    },
                    states: {
                        hover: {
                            enabled: true
                        }
                    }
                }
            },
            series: [{
                name: 'Total Value',
                color: 'blue'
            }, {
                name: 'Total Contributions',
                color: 'orange',
                step: 'left'
            }, {
                name: 'Net Growth',
                color: 'lime',
                negativeColor: 'red'
            }],
            title: {
                text: 'Portfolio Value Over Time'
            },
            tooltip: {
                split: false,
                shared: true
            },
            xAxis: {
                type: 'datetime',
            },
            yAxis: {
                plotLines: [{
                    value: 0,
                    width: 2,
                    color: 'black'
                }]
            }
        });
    });
    </script>
    '''

    def get_data(self, **kwargs):
        days, values, deposits, growth = self.userprofile.get_growth_data()
        return list(zip(days, values, deposits, growth))


class DailyChangeChart(BaseHighChart):
    container_name = 'change-div'
    data_param = 'change'
    _JAVASCRIPT_TEMPLATE = '''    
    <script src="https://code.highcharts.com/stock/indicators/indicators.js"></script>
    <script>
    $.get("?chart=$data_param", function(data) {
       Highcharts.StockChart({
           boost: {
               useGPUTranslations: true
           },
           chart: {
               renderTo: "$container_name",
               width: 700,
               height: 500,
               type: 'scatter',
               zoomType: 'xy'
           },
           credits: {
               enabled: false
           },
           data: {
               firstRowAsNames: false,
               rows: data
           },
           legend: {
               enabled: true
           },
           plotOptions: {
               series: {
                   tooltip: {
                       valueDecimals: 2
                   }
               }
           },
           series: [{
                   type: 'scatter',
                   id: 'growth',
                   color: 'royalblue',
                   marker: {
                       radius: 2,
                       symbol: 'circle'
                   },
                   name: 'Daily growth',
                   tooltip: {
                       headerFormat: '<span style=\"font-size: 10px\">{point.key}</span><br/>',
                       pointFormatter: function() {
                           var rounded = Math.round(this.y, 2);                            
                           if (rounded >= 0) {
                               return "Gain: <b>$" + rounded + "</b>";
                           }
                           return "Loss: <b>$(" + Math.abs(rounded) + ")</b>";
                       }
                   }
               },
               {
                   type: 'sma',
                   color: 'lime',
                   name: '90 Day Average Daily Profit',
                   linkedTo: 'growth',
                   negativeColor: 'red',
                   params: {
                       period: 90
                   },
                   tooltip: {
                       pointFormat: '<span style="color:{point.color}">\u25cf</span> {series.name}: <b>${point.y:.2f}</b><br/>'
                   }
               }
           ],
           title: {
               text: 'Daily Gain/Loss'
           },
           tooltip: {
               split: false,
               shared: true
           },
           xAxis: {
               type: 'datetime'
           },
           yAxis: {
               plotLines: [{
                   value: 0,
                   width: 2,
                   color: 'black'
               }]
           }
       });
    });
    </script>
    '''

    def get_data(self, **kwargs):
        from utils.misc import window

        days, values, deposits, growth = self.userprofile.get_growth_data()
        daily_growth = [t - y for y, t in window(growth)]
        return list(zip(days, daily_growth))


class SecurityChart(BaseHighChart):
    container_name = 'security-div'
    data_param = 'security'
    _JAVASCRIPT_TEMPLATE = '''    
    <script src="https://code.highcharts.com/stock/indicators/indicators.js"></script>
    <script>
    $.get("?chart=$data_param", function(series) {
        Highcharts.StockChart({
            boost: {
                useGPUTranslations: true
            },
            chart: {
                renderTo: "$container_name",
                width: 1000,
                height: 500,
                type: 'line',
                zoomType: 'x'
            },
            credits: {
                enabled: false
            },
            legend: {
                enabled: true,
            },
            plotOptions: {
                series: {
                    dataGrouping: {
                        units: [
                            ['day', [1]],
                            ['week', [1]],
                            ['month', [1]]
                        ],
                        approximation: function (arr){
                            return Math.max(...arr);
                        },
                        enabled:true,
                        groupPixelWidth:5
                    },
                    tooltip: {
                        valueDecimals: 2
                    }
                }
            },
            series: series,
            title: {
                text: '$symbol'
            },
            tooltip: {
                split: false,
                shared: true,
                xDateFormat: '%A, %b %e, %Y'
            }
        });
    });
    </script>
    '''

    def __init__(self, userprofile, security=None):
        super().__init__(userprofile)
        self.security = security
        self.symbol = security.symbol

    def get_data(self):
        def to_ts(d):
            return datetime.combine(d, time.min).timestamp() * 1000

        series = []
        series.append({
            'name': 'Price',
            'data': [(to_ts(d), float(p)) for d, p in self.security.prices.values_list('day', 'price')],
            'color': 'blue',
            'id': 'price'
        })

        userprofile = self.userprofile
        activities = userprofile.GetActivities().for_security(self.security)
        purchase_data = activities.transactions().values('trade_date').annotate(total_qty=Sum('qty'), ).values_list(
            'trade_date', 'total_qty', 'price')
        series.append({
            'name': 'Purchases',
            'type': 'flags',
            'shape': 'squarepin',
            'onSeries': 'price',
            'allowOverlapX': True,
            'data': [{'x': to_ts(day),
                      'fillColor': 'GreenYellow' if qty > 0 else 'red',
                      'title': str(int(qty)),
                      'text': '{} {:.0f} @ {:.2f}'.format('Buy' if qty > 0 else 'Sell', qty, price),
                      } for day, qty, price in purchase_data]
        })
        series.append({
            'name': 'Dividends',
            'type': 'flags',
            'fillColor': 'LightCyan',
            'shape': 'circlepin',
            'allowOverlapX': True,
            'data': [{'x': to_ts(day),
                      'title': '{:.2f}'.format(price),
                      'text': 'Dividend of ${:.2f}'.format(price),
                      } for day, price in activities.dividends().values_list('trade_date', 'price').distinct()]

        })
        return series

