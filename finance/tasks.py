from celery import shared_task

@shared_task
def LiveSecurityUpdateTask():
    from securities.models import Security, Currency
    from .models import BaseClient, HoldingDetail
    Security.objects.Sync()
    Currency.objects.Sync()
    BaseClient.objects.SyncAllBalances()
    HoldingDetail.Refresh()

@shared_task
def RefreshClientTask(user=None):
    from .models import BaseClient
    clients = user.clients.all() if user else BaseClient.objects.all()
    for client in clients:
        with client:
            client.Refresh()
