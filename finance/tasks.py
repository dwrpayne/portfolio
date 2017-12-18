from celery import shared_task

@shared_task
def LiveSecurityUpdateTask():
    from securities.models import Security
    from .models import BaseClient, HoldingDetail
    Security.objects.Sync()
    BaseClient.objects.SyncAllBalances()
    HoldingDetail.Refresh()

@shared_task
def SyncActivityTask(user=None):
    from .models import BaseAccount, HoldingDetail
    for account in BaseAccount.objects.for_user(user):
        account.SyncAndRegenerate()

@shared_task
def DailyUpdateAll():
    SyncActivityTask()
    LiveSecurityUpdateTask()
