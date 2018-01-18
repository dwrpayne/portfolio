from django.db.models.signals import post_save
from django.conf import settings
from django.dispatch import receiver

from .models import UserProfile

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, **kwargs):
    user = instance
    if kwargs["created"]:
        user_profile = UserProfile(user=user)
        user_profile.save()
