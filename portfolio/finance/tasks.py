from .models import BaseClient
from celery import shared_task

@shared_task
def SyncClientPrices(client_id):
    with BaseClient.objects.get(pk=client_id) as client:
        client.SyncPrices()

@shared_task
def SyncClientAccountBalances(client_id):
    with BaseClient.objects.get(pk=client_id) as client:
        client.SyncCurrentAccountBalances()

