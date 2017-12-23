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
    HoldingDetail.Refresh()
    SyncAccountBalanceTask()

@shared_task
def SyncActivityTask(userprofile=None):
    from .models import BaseAccount
    accounts = userprofile.GetAccounts() if userprofile else BaseAccount.objects.all()
    accounts.SyncAllActivitiesAndRegenerate()

@shared_task
def DailyUpdateAll():
    from .models import HoldingDetail
    SyncActivityTask()
    SyncSecurityTask()
    HoldingDetail.Refresh()
    SyncAccountBalanceTask()
