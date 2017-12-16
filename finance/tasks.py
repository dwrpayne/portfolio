from celery import shared_task

@shared_task
def LiveSecurityUpdateTask():
    from securities.models import Stock, MutualFund, Cash
    from .models import BaseClient, HoldingDetail
    Stock.objects.SyncLive()
    MutualFund.objects.Sync()
    Cash.objects.Sync()
    BaseClient.objects.SyncAllBalances()
    HoldingDetail.Refresh()
            
@shared_task
def DailyUpdateTask():
    from securities.models import Stock, MutualFund, Cash, Option
    from .models import BaseClient, HoldingDetail
    Stock.objects.Sync()
    Option.objects.Sync()        
    MutualFund.objects.Sync()
    Cash.objects.Sync()
    BaseClient.objects.SyncAllBalances()
    HoldingDetail.Refresh()

@shared_task
def RefreshClientTask(user=None):
    from .models import BaseClient
    clients = user.clients.all() if user else BaseClient.objects.all()
    for client in clients:
        with client:
            client.Refresh()
