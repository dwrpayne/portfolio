from django.contrib import admin
from django.template.defaultfilters import floatformat

from .models import QuestradeClient, QuestradeAccount, Activity, Holding, SecurityPrice, Security, ExchangeRate, Currency, QuestradeRawActivity

def MakeNormalizedFloat(field, desc):
    def display(self, obj, field=field):
        return getattr(obj, field).normalize()
    display.short_description = desc
    display.admin_order_field = field
    return display

class ActivityAdmin(admin.ModelAdmin):    
    display_qty = MakeNormalizedFloat('qty', 'Quantity')
    display_price = MakeNormalizedFloat('price', 'Price')

    list_display = ['account', 'tradeDate', 'type', 'security', 'display_qty', 'display_price', 'cash', 'netAmount']
    list_filter = ['account', 'tradeDate', ('security', admin.RelatedOnlyFieldListFilter), 'type', ('cash', admin.RelatedOnlyFieldListFilter)]        
    search_fields = ['description']
admin.site.register(Activity, ActivityAdmin)

class QuestradeRawActivityAdmin(admin.ModelAdmin):
    list_display = ['account', 'jsonstr', 'cleaned']
    list_filter = ['account']      
admin.site.register(QuestradeRawActivity, QuestradeRawActivityAdmin)


class AccountAdmin(admin.ModelAdmin):
    list_display = ['client', 'type', 'id']
admin.site.register(QuestradeAccount, AccountAdmin)
    
class HoldingAdmin(admin.ModelAdmin):
    display_qty = MakeNormalizedFloat('qty', 'Quantity')
    list_display = ['account', 'security', 'display_qty', 'startdate', 'enddate']
    list_filter = ['account', 'security', 'enddate']      
admin.site.register(Holding, HoldingAdmin)

class ClientAdmin(admin.ModelAdmin):
    list_display = ['username']
admin.site.register(QuestradeClient, ClientAdmin)
    

class CurrencyAdmin(admin.ModelAdmin):
    list_display = ['code', 'lookupSymbol', 'lookupSource', 'lookupColumn', 'live_price']
admin.site.register(Currency, CurrencyAdmin)

class SecurityAdmin(admin.ModelAdmin):
    def latest_update_day(self, obj):
        return obj.rates.latest().day
    latest_update_day.short_description = "Latest Price"
    list_display = ['symbol', 'symbolid', 'type', 'currency', 'live_price', 'latest_update_day', 'description']
admin.site.register(Security, SecurityAdmin)

class SecurityPriceAdmin(admin.ModelAdmin):
    list_display = ['security', 'day', 'price']
    list_filter = ['day', 'security']        
admin.site.register(SecurityPrice, SecurityPriceAdmin)

class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ['currency', 'day', 'price']
    list_filter = ['day', 'currency']        
admin.site.register(ExchangeRate, ExchangeRateAdmin)
