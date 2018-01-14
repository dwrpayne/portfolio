from django.db.models.signals import pre_save
from django.dispatch import receiver

from .models import AlphaVantageDataSource


@receiver(pre_save, sender=AlphaVantageDataSource)
def validate_alphavantage_symbol(sender, instance, **kwargs):
    instance.validate_symbol()
