from celery import shared_task
from .models import QuestradeClient

@shared_task
def RefreshAccessToken(client_id):
    QuestradeClient.objects.get(pk=client_id).Authorize()