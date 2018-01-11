from django.contrib import admin

from .models import RbcClient, RbcAccount, RbcRawActivity

admin.site.register(RbcClient)
admin.site.register(RbcRawActivity)

class RbcAccountAdmin(admin.ModelAdmin):
    list_display = ['client', 'type', 'id']

admin.site.register(RbcAccount, RbcAccountAdmin)

