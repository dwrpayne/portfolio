from datetime import date

from django.contrib import messages

from .models import Holding
from .tasks import SyncSecurityTask


def check_for_missing_securities(request):
    current = Holding.objects.current().values_list('security_id').distinct()
    num_prices = current.filter(security__prices__day=date.today()).count()
    if current.count() > num_prices:
        messages.warning(request, 'Currently updating out-of-date stock data. Please try again in a few seconds.'.format(num_prices, current.count()))
        messages.debug(request, '{} of {} synced'.format(num_prices, current.count()))
        SyncSecurityTask.delay(False)


class RefreshButtonHandlerMixin:
    """
    Mixin to add support for my custom refresh button.
    """
    def get(self, request, *args, **kwargs):
        if request.is_ajax():
            key = next(key for key in request.GET if key.startswith('refresh-'))
            _, *actions = key.split('-')
            return self.ajax_request(request, actions)
        return super().get(request, *args, **kwargs)

    def ajax_request(self, request, action):
        pass

