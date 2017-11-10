from django.contrib import admin

from .models import TangerineClient, TangerineRawActivity, TangerineAccount

class TangerineRawActivityAdmin(admin.ModelAdmin):      
    list_display = ['account', 'day', 'security', 'qty', 'price', 'description']
admin.site.register(TangerineRawActivity, TangerineRawActivityAdmin)

class TangerineAccountAdmin(admin.ModelAdmin):    
    list_display = ['client', 'type', 'id', 'display_name']
admin.site.register(TangerineAccount, TangerineAccountAdmin)

class TangerineClientAdmin(admin.ModelAdmin):    
    list_display = ['username']
admin.site.register(TangerineClient, TangerineClientAdmin)
