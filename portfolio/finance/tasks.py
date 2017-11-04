from .models import BaseClient, Security, DataProvider
from celery import shared_task
from celery import group
from celery.result import allow_join_result

@shared_task
def SyncClientPrices(client_id):
    with BaseClient.objects.get(pk=client_id) as client:
        client.SyncPrices()

@shared_task
def SyncClientAccountBalances(client_id):
    with BaseClient.objects.get(pk=client_id) as client:
        client.SyncCurrentAccountBalances()

@shared_task
def UpdatePrice(symbol):
    Security.stocks.get(symbol=symbol).SyncRates(DataProvider.GetAlphaVantageData)
    
@shared_task
def UpdateDailyPrices():
    with allow_join_result():
        tasks = [UpdatePrice.s(stock.symbol) for stock in Security.stocks.all()]
        tasks += [SyncClientPrices.s(client.username) for client in BaseClient.objects.all()]
        tasks += [SyncClientAccountBalances.s(client.username) for client in BaseClient.objects.all()]
        res = group(tasks)()
        res.get()
    DataProvider.SyncAllSecurities()
    DataProvider.UpdateLatestExchangeRates()