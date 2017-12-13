from celery import shared_task
from celery import group
from requests.exceptions import ConnectionError

@shared_task
def LiveSecurityUpdateTask():
    from .models import Stock, MutualFund, Cash, Option, BaseClient, HoldingDetail
    Stock.objects.SyncLive()
    MutualFund.objects.Sync()
    Cash.objects.Sync()
    BaseClient.objects.SyncAllBalances()
    HoldingDetail.Refresh()
            
@shared_task
def DailyUpdateTask():
    from .models import Stock, MutualFund, Cash, Option, BaseClient, HoldingDetail
    Stock.objects.Sync()
    Option.objects.Sync()        
    MutualFund.objects.Sync()
    Cash.objects.Sync()
    BaseClient.objects.SyncAllBalances()
    HoldingDetail.Refresh()
