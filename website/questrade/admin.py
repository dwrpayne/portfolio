from django.contrib import admin
from django.template.defaultfilters import floatformat

from .models import Client, Account, Activity, ExchangeRate, StockPrice

class ActivityAdmin(admin.ModelAdmin):    
    def display_qty(self, obj):
        return obj.qty.normalize()
    display_qty.short_description = 'Quantity'
    display_qty.admin_order_field = 'qty'

    def display_price(self, obj):
        return obj.price.normalize()
    display_price.short_description = 'Price'
    display_price.admin_order_field = 'price'

    list_display = ['account', 'tradeDate', 'type', 'action', 'symbol', 'display_qty', 'display_price', 'netAmount', 'description']
    list_filter = ['tradeDate', 'symbol', 'type']        
    search_fields = ['description']
admin.site.register(Activity, ActivityAdmin)



class AccountAdmin(admin.ModelAdmin):
    list_display = ['client', 'type', 'account_id']
admin.site.register(Account, AccountAdmin)



admin.site.register(Client)



class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ['basecurrency', 'currency', 'date', 'value']
    list_filter = ['basecurrency', 'currency', 'date']        
admin.site.register(ExchangeRate, ExchangeRateAdmin)



class StockPriceAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'date', 'value']
    list_filter = ['date', 'symbol']        
admin.site.register(StockPrice, StockPriceAdmin)