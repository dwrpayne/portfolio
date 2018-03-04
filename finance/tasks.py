from celery import shared_task

@shared_task
def SyncSecurityTask(live_update=False):
    from securities.models import Security
    from .models import HoldingDetail
    Security.objects.Sync(live_update)
    HoldingDetail.Refresh()

@shared_task
def SyncActivityTask(userprofile=None):
    from .models import BaseAccount, HoldingDetail
    accounts = userprofile.GetAccounts() if userprofile else BaseAccount.objects.all()
    accounts.SyncAllActivitiesAndRegenerate()
    HoldingDetail.Refresh()

@shared_task
def DailyUpdateAll():
    SyncActivityTask()
    SyncSecurityTask()

@shared_task
def HandleCsvUpload(accountcsv_id):
    from .models import AccountCsv, HoldingDetail
    a = AccountCsv.objects.get(pk=accountcsv_id)
    a.account.import_activities(a.csvfile)
    HoldingDetail.Refresh()
