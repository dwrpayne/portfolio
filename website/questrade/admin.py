from django.contrib import admin
from django.template.defaultfilters import floatformat

from .models import Client, Account, Activity, Holding, SecurityPrice, Security

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
    list_display = ['account', 'security', 'display_qty', 'startdate', 'enddate']
admin.site.register(Holding, HoldingAdmin)

admin.site.register(Client)
admin.site.register(Security)

class SecurityPriceAdmin(admin.ModelAdmin):
    list_display = ['security', 'date', 'price']
    list_filter = ['date', 'security']        
admin.site.register(SecurityPrice, SecurityPriceAdmin)