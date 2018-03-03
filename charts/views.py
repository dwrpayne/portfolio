from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin


class GrowthChart(LoginRequiredMixin, View):
    container_name = 'growth-div'
    url_name = 'growth'
    app = 'charts'
    javascript = '''
    <script src="https://code.highcharts.com/modules/data.js"></script>
    <script>
    $.get("{% url '$app:$url_name' %}", function(growthdata) {
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
                rows: growthdata
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
    });Total Value',
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
    </script>
    '''

    @classmethod
    def get_javascript(cls):
        from string import Template
        s = Template(cls.javascript)
        return s.safe_substitute(cls.__dict__)

    def get(self, request, *args, **kwargs):
        if request.is_ajax():
            return self.get_data(request.user.userprofile)
        return super().get(request, *args, **kwargs)

    def get_data(self, userprofile):
        from finance.services import get_growth_data
        from utils.misc import window

        days, values, deposits, growth = get_growth_data(userprofile)
        daily_growth = [t - y for y, t in window(growth)]
        return list(zip(days, daily_growth))
