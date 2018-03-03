from django.http import JsonResponse
from .models import BaseHighChart


class HighChartMixin:
    """
    Any view that wants to display a HighChart should inherit from this.
    """
    def get(self, request, *args, **kwargs):
        if request.is_ajax():
            chart_type = request.GET.get('chart', '')
            my_charts = []
            for att in vars(self):
                obj = getattr(self, att)
                if hasattr(obj, '_is_highchart_model'):
                    my_charts.append(obj)
            for chart in my_charts:
                if chart_type == chart.data_param:
                    return JsonResponse(chart.get_data(), safe=False)
        return super().get(request, *args, **kwargs)
