from celery import shared_task

@shared_task
def SyncSecurityTask(live_update=False):
    from securities.models import Security
    Security.objects.Sync(live_update)

@shared_task
def SyncAccountBalanceTask():
    from .models import BaseAccount
    BaseAccount.objects.SyncAllBalances()

@shared_task
def LiveSecurityUpdateTask():
    from .models import HoldingDetail
    SyncSecurityTask(live_update=True)
    SyncAccountBalanceTask()
    HoldingDetail.Refresh()

@shared_task
def SyncActivityTask(user=None):
    from .models import BaseAccount
    BaseAccount.objects.SyncActivitiesAndRegenerate(user)

@shared_task
def DailyUpdateAll():
    from .models import HoldingDetail
    SyncActivityTask()
    SyncSecurityTask()
    SyncAccountBalanceTask()
    HoldingDetail.Refresh()
