from celery import shared_task
from celery import group
from requests.exceptions import ConnectionError

@shared_task
def LiveSecurityUpdateTask():
    from .models import HoldingDetail, BaseClient, Stock, MutualFund, Cash
    Stock.objects.SyncLive()
    MutualFund.objects.Sync()
    Cash.objects.Sync()
    HoldingDetail.Refresh()
    for client in BaseClient.objects.all():
        with client:
            client.SyncCurrentAccountBalances()
            
@shared_task
def DailyUpdateTask():
    from .models import Currency, Stock, MutualFund, Cash, Option
    Stock.objects.Sync()
    Option.objects.Sync()        
    MutualFund.objects.Sync()
    Cash.objects.Sync()
    HoldingDetail.Refresh()
