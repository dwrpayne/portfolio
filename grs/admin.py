from django.contrib import admin

from .models import GrsClient, GrsRawActivity, GrsAccount, GrsDataSource

admin.site.register(GrsClient)


class GrsRawActivityAdmin(admin.ModelAdmin):
    list_display = ['account', 'day', 'symbol', 'qty', 'price']

admin.site.register(GrsRawActivity, GrsRawActivityAdmin)


class GrsAccountAdmin(admin.ModelAdmin):
    list_display = ['client', 'type', 'id']

admin.site.register(GrsAccount, GrsAccountAdmin)

class GrsDataSourceAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'plan_data']

admin.site.register(GrsDataSource, GrsDataSourceAdmin)
