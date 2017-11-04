from celery import shared_task
from .models import QuestradeClient

@shared_task
def RefreshAccessTokens():
    for c in QuestradeClient.objects.all():
        c.Authorize()