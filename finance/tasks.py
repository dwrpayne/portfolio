from celery import shared_task
from celery import group
from requests.exceptions import ConnectionError

@shared_task
def LiveSecurityUpdateTask():
    from .models import DataProvider, HoldingDetail, BaseClient
    DataProvider.SyncLiveSecurities()
    HoldingDetail.Refresh()
    for client in BaseClient.objects.all():
        with client:
            client.SyncPrices()
            client.SyncCurrentAccountBalances()
            
@shared_task
def LiveExchangeUpdateTask():
    from .models import DataProvider
    DataProvider.SyncAllExchangeRates()

@shared_task
def DailyUpdateTask():
    from .models import DataProvider
    DataProvider.SyncAllExchangeRates()
    DataProvider.SyncAllSecurities()


def GetLiveUpdateTaskGroup(user):
    tasks = [LiveSecurityUpdateTask.si()]
    return group(tasks)
