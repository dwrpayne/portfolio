from .models import BaseClient, Security, DataProvider
from celery import shared_task
from celery import group
from celery.result import allow_join_result
from requests.exceptions import ConnectionError

@shared_task(max_retries=5, default_retry_delay=5, autoretry_for=(ConnectionError,))
def SyncClientPrices(client_id):
    with BaseClient.objects.get(pk=client_id) as client:
        client.SyncPrices()

@shared_task(max_retries=5, default_retry_delay=5, autoretry_for=(ConnectionError,))
def SyncClientAccountBalances(client_id):
    with BaseClient.objects.get(pk=client_id) as client:
        client.SyncCurrentAccountBalances()

@shared_task
def SyncPrices(symbol):
    Security.stocks.get(symbol=symbol).SyncRates(DataProvider.GetAlphaVantageData)
    
@shared_task
def UpdateExchange():
    DataProvider.SyncAllExchangeRates()

@shared_task
def UpdatePrices(symbol):
    price = DataProvider.GetLiveStockPrice(symbol)
    if price:
        s = Security.stocks.get(symbol=symbol)
        s.live_price = price

@shared_task
def LiveUpdateTask():
    DataProvider.SyncAllExchangeRates()
    DataProvider.SyncLiveSecurities()

def GetLiveUpdateTaskGroup():
    tasks = [UpdateExchange.si()]
    tasks += [UpdatePrices.si(symbol) for symbol in Security.stocks.filter(holdings__enddate=None).distinct().values_list('symbol', flat=True)]
    return group(tasks)
    
def GetDailyUpdateTaskGroup():    
    livegroup = GetLiveUpdateTaskGroup()

    tasks = [SyncClientPrices.s(client.username) for client in BaseClient.objects.all()]
    tasks += [SyncClientAccountBalances.s(client.username) for client in BaseClient.objects.all()]
    tasks += [SyncPrices.s(stock.symbol) for stock in Security.stocks.all()]

    return group(tasks)
