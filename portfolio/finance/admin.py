from django.contrib import admin

from .models import ManualRawActivity, BaseRawActivity, BaseAccount, BaseClient

class ManualRawActivityAdmin(admin.ModelAdmin):    
    list_display = ['account', 'day', 'type', 'security', 'qty', 'price', 'cash', 'netAmount']    
admin.site.register(ManualRawActivity, ManualRawActivityAdmin)


admin.site.register(BaseRawActivity)
admin.site.register(BaseAccount)
admin.site.register(BaseClient)