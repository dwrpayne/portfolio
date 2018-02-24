from django.contrib import admin
from .models import Security, SecurityPrice


class SecurityAdmin(admin.ModelAdmin):
    def latest_update_day(self, obj):
        return obj.prices.latest().day

    def first_update_day(self, obj):
        return obj.prices.earliest().day

    latest_update_day.short_description = "Latest Price"
    list_filter = ['currency', 'type']
    list_display = ['symbol', 'type', 'currency', 'live_price',
                    'first_update_day', 'latest_update_day', 'get_datasource_list']


admin.site.register(Security, SecurityAdmin)


class SecurityPriceAdmin(admin.ModelAdmin):
    list_display = ['security', 'day', 'price']
    list_filter = ['day', 'security']


admin.site.register(SecurityPrice, SecurityPriceAdmin)
