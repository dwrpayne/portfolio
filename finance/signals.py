from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Holding, Allocation


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, created, **kwargs):
    if created:
        user = instance
        from .models import UserProfile
        UserProfile.objects.create(user=user)

@receiver(post_save, sender=Holding)
def create_holding(sender, instance, created, **kwargs):
    if True:#created:
        holding = instance
        Allocation.objects.ensure_allocated(holding.security_id, holding.account.user)
