from django.http import JsonResponse
from .models import BaseHighChart


class HighChartMixin:
    """
    Any view that wants to display a HighChart should inherit from this.
    chart_classes: a list of classes to instantiate. template var will default to the lower cased name.
    get_chart_kwargs: override this to pass extra args into get_data()
    """
    chart_classes = []
    chart_objects = []

    def get(self, request, *args, **kwargs):
        for cls in self.chart_classes:
            obj = cls(self.request.user.userprofile)
            setattr(self, cls.__name__.lower(), obj)
            self.chart_objects.append(obj)

        if request.is_ajax():
            chart_type = request.GET.get('chart', '')
            for chart in self.chart_objects:
                if chart_type == chart.data_param:
                    data = chart.get_data(**self.get_chart_kwargs(request))
                    return JsonResponse(data, safe=False)
        return super().get(request, *args, **kwargs)

    def get_chart_kwargs(self, request):
        return dict()
