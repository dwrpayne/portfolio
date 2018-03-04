from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, **kwargs):
    user = instance
    if kwargs["created"]:
        from .models import UserProfile
        user_profile = UserProfile(user=user)
        user_profile.save()
