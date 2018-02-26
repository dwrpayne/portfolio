from django.db.models.signals import pre_save
from django.dispatch import receiver

from .models import AlphaVantageStockSource


@receiver(pre_save, sender=AlphaVantageStockSource)
def validate_alphavantage_symbol(sender, instance, **kwargs):
    instance.validate_symbol()
