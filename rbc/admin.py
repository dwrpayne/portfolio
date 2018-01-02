from django.contrib import admin

from .models import RbcClient, RbcAccount

admin.site.register(RbcClient)

class RbcAccountAdmin(admin.ModelAdmin):
    list_display = ['client', 'type', 'id']

admin.site.register(RbcAccount, RbcAccountAdmin)

