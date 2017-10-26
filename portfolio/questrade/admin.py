from django.contrib import admin
from django.template.defaultfilters import floatformat

from .models import Client, Account, Activity, Holding, SecurityPrice, Security, ExchangeRate, Currency

def MakeNormalizedFloat(field, desc):
    def display(self, obj, field=field):
        return getattr(obj, field).normalize()
    display.short_description = desc
    display.admin_order_field = field
    return display

class ActivityAdmin(admin.ModelAdmin):    
    display_qty = MakeNormalizedFloat('qty', 'Quantity')
    display_price = MakeNormalizedFloat('price', 'Price')

    list_display = ['account', 'tradeDate', 'type', 'action', 'security', 'display_qty', 'display_price', 'netAmount', 'grossAmount', 'description']
    list_filter = ['account', 'tradeDate', 'security', 'type']        
    search_fields = ['description']
admin.site.register(Activity, ActivityAdmin)


class AccountAdmin(admin.ModelAdmin):
    list_display = ['client', 'type', 'id']
admin.site.register(Account, AccountAdmin)
    
class HoldingAdmin(admin.ModelAdmin):
    display_qty = MakeNormalizedFloat('qty', 'Quantity')
    list_display = ['account', 'securitybase', 'display_qty', 'startdate', 'enddate']
    list_filter = ['account', 'securitybase', 'enddate']        

admin.site.register(Holding, HoldingAdmin)

admin.site.register(Client)

class CurrencyAdmin(admin.ModelAdmin):
    list_display = ['code', 'rateLookup']
admin.site.register(Currency, CurrencyAdmin)

class SecurityAdmin(admin.ModelAdmin):
    def security_price_count(self, obj):
        return obj.securityprice_set.latest().day
    security_price_count.short_description = "Latest Price"
    list_display = ['symbol', 'symbolid', 'type', 'security_currency', 'listingExchange', 'description', 'security_price_count']
admin.site.register(Security, SecurityAdmin)

class SecurityPriceAdmin(admin.ModelAdmin):
    list_display = ['security', 'day', 'price']
    list_filter = ['day', 'security']        
admin.site.register(SecurityPrice, SecurityPriceAdmin)

class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ['currency', 'day', 'price']
    list_filter = ['day', 'currency']        
admin.site.register(ExchangeRate, ExchangeRateAdmin)