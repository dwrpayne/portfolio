from django.contrib import admin
from .models import Currency, ExchangeRate, Security, SecurityPrice

class CurrencyAdmin(admin.ModelAdmin):
    list_display = ['code', 'live_price']


admin.site.register(Currency, CurrencyAdmin)


class SecurityAdmin(admin.ModelAdmin):
    def latest_update_day(self, obj):
        return obj.rates.latest().day

    def first_update_day(self, obj):
        return obj.rates.earliest().day
    latest_update_day.short_description = "Latest Price"
    list_filter = ['currency', 'type']
    list_display = ['symbol', 'type', 'currency', 'live_price',
                    'first_update_day', 'latest_update_day', 'description']


admin.site.register(Security, SecurityAdmin)


class SecurityPriceAdmin(admin.ModelAdmin):
    list_display = ['security', 'day', 'price']
    list_filter = ['day', 'security']


admin.site.register(SecurityPrice, SecurityPriceAdmin)


class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ['currency', 'day', 'price']
    list_filter = ['day', 'currency']


admin.site.register(ExchangeRate, ExchangeRateAdmin)
