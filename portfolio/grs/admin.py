from django.contrib import admin

from .models import Client, ActivityRaw, Account

admin.site.register(Client)

class ActivityRawAdmin(admin.ModelAdmin):    
    list_display = ['account', 'day', 'security', 'qty', 'price']
admin.site.register(ActivityRaw, ActivityRawAdmin)

class AccountAdmin(admin.ModelAdmin):    
    list_display = ['client', 'type', 'id', 'plan_data']
admin.site.register(Account, AccountAdmin)
