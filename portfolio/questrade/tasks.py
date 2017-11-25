from celery import shared_task

@shared_task
def RefreshAccessTokens():
    from .models import QuestradeClient
    for c in QuestradeClient.objects.all():
        c.Authorize()


        