from django.contrib import admin
from django.template.defaultfilters import floatformat

from .models import Client, Account, Activity, ExchangeRate, Holding, StockPrice

def MakeNormalizedFloat(field, desc):
    def display(self, obj, field=field):
        return getattr(obj, field).normalize()
    display.short_description = desc
    display.admin_order_field = field
    return display

class ActivityAdmin(admin.ModelAdmin):    
    display_qty = MakeNormalizedFloat('qty', 'Quantity')
    display_price = MakeNormalizedFloat('price', 'Price')

    list_display = ['account', 'tradeDate', 'type', 'action', 'symbol', 'display_qty', 'display_price', 'netAmount', 'description']
    list_filter = ['account', 'tradeDate', 'symbol', 'type']        
    search_fields = ['description']
admin.site.register(Activity, ActivityAdmin)


class AccountAdmin(admin.ModelAdmin):
    list_display = ['client', 'type', 'id']
admin.site.register(Account, AccountAdmin)
    
class HoldingAdmin(admin.ModelAdmin):
    display_qty = MakeNormalizedFloat('qty', 'Quantity')
    list_display = ['account', 'symbol', 'display_qty', 'startdate', 'enddate']
admin.site.register(Holding, HoldingAdmin)

admin.site.register(Client)



class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ['basecurrency', 'currency', 'date', 'value']
    list_filter = ['basecurrency', 'currency', 'date']        
admin.site.register(ExchangeRate, ExchangeRateAdmin)



class StockPriceAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'date', 'value']
    list_filter = ['date', 'symbol']        
admin.site.register(StockPrice, StockPriceAdmin)