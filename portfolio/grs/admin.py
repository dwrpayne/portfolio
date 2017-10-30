from django.contrib import admin

from .models import GrsClient, GrsActivityRaw, GrsAccount

admin.site.register(GrsClient)

class GrsActivityRawAdmin(admin.ModelAdmin):    
    list_display = ['account', 'day', 'security', 'qty', 'price']
admin.site.register(GrsActivityRaw, GrsActivityRawAdmin)

class GrsAccountAdmin(admin.ModelAdmin):    
    list_display = ['client', 'type', 'id', 'plan_data']
admin.site.register(GrsAccount, GrsAccountAdmin)
