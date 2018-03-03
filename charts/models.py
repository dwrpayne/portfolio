from django.db import models

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
        return s.safe_substitute({'data_param': self.data_param,
                                  'container_name': self.container_name})

    def get_data(self):
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

    def get_data(self):
        from finance.services import get_growth_data
        return list(zip(*get_growth_data(self.userprofile)))


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

    def get_data(self):
        from finance.services import get_growth_data
        from utils.misc import window

        days, values, deposits, growth = get_growth_data(self.userprofile)
        daily_growth = [t - y for y, t in window(growth)]
        return list(zip(days, daily_growth))


class SecurityChartBase(BaseHighChart):
    container_name = 'change-div'
    data_param = 'change'
    _JAVASCRIPT_TEMPLATE = '''    
    <script src="https://code.highcharts.com/stock/indicators/indicators.js"></script>
    <script>
    $.get("{% url 'finance:securitychart' security %}", function(series) {
        Highcharts.StockChart({
            boost: {
                useGPUTranslations: true
            },
            chart: {
                renderTo: "securitycontainer",
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
                text: '{{ security.symbol }}'
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

    def get_data(self):
        from finance.services import get_growth_data
        from utils.misc import window

        days, values, deposits, growth = get_growth_data(self.userprofile)
        daily_growth = [t - y for y, t in window(growth)]
        return list(zip(days, daily_growth))
