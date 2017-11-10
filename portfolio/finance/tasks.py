from celery import shared_task
from celery import group
from requests.exceptions import ConnectionError

@shared_task(max_retries=5, default_retry_delay=5, autoretry_for=(ConnectionError,))
def SyncClientPrices(client_id):
    from .models import BaseClient
    for client in BaseClient.objects.all():
        with client:
            client.SyncPrices()

@shared_task(max_retries=5, default_retry_delay=5, autoretry_for=(ConnectionError,))
def SyncClientAccountBalances(client_id):
    from .models import BaseClient
    with BaseClient.objects.get(pk=client_id) as client:
        client.SyncCurrentAccountBalances()

@shared_task
def SyncPrices(symbol):
    from .models import DataProvider
    DataProvider.SyncAllSecurities()
    
@shared_task
def LiveUpdateTask():
    from .models import DataProvider
    DataProvider.SyncAllExchangeRates()
    DataProvider.SyncLiveSecurities()
    
@shared_task
def DailyUpdateTask():
    from .models import BaseClient, DataProvider
    for client in BaseClient.objects.all():
        SyncClientPrices(client.id)
    DataProvider.SyncAllSecurities()

def GetLiveUpdateTaskGroup(user):
    tasks = [LiveUpdateTask.si()]
    tasks += [SyncClientAccountBalances.s(client.id) for client in user.clients.all()]
    return group(tasks)
    