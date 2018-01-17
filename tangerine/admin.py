from django.contrib import admin

from .models import TangerineRawActivity, TangerineAccount


class TangerineRawActivityAdmin(admin.ModelAdmin):
    list_display = ['account', 'day', 'symbol', 'qty', 'price', 'description']


admin.site.register(TangerineRawActivity, TangerineRawActivityAdmin)


class TangerineAccountAdmin(admin.ModelAdmin):
    list_display = ['user', 'type', 'id', 'display_name']


admin.site.register(TangerineAccount, TangerineAccountAdmin)


class TangerineClientAdmin(admin.ModelAdmin):
    list_display = ['username']

#
# admin.site.register(TangerineClient, TangerineClientAdmin)
