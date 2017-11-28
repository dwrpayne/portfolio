from django.contrib import admin

from .models import GrsClient, GrsRawActivity, GrsAccount

admin.site.register(GrsClient)


class GrsRawActivityAdmin(admin.ModelAdmin):
    list_display = ['account', 'day', 'security', 'qty', 'price']
admin.site.register(GrsRawActivity, GrsRawActivityAdmin)


class GrsAccountAdmin(admin.ModelAdmin):
    list_display = ['client', 'type', 'id', 'plan_data']
admin.site.register(GrsAccount, GrsAccountAdmin)
