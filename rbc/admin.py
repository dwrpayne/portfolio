from django.contrib import admin

from .models import RbcAccount, RbcRawActivity

admin.site.register(RbcRawActivity)

class RbcAccountAdmin(admin.ModelAdmin):
    list_display = ['user', 'type', 'id']

admin.site.register(RbcAccount, RbcAccountAdmin)

