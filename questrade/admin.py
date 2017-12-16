from django.contrib import admin

from .models import QuestradeClient, QuestradeAccount, QuestradeRawActivity, QuestradeActivityType


class QuestradeActivityTypeAdmin(admin.ModelAdmin):
    list_display = ['q_type', 'q_action', 'activity_type']

admin.site.register(QuestradeActivityType, QuestradeActivityTypeAdmin)


class QuestradeRawActivityAdmin(admin.ModelAdmin):
    list_display = ['account', 'jsonstr']
    list_filter = ['account']
    search_fields = ['jsonstr']

admin.site.register(QuestradeRawActivity, QuestradeRawActivityAdmin)


class AccountAdmin(admin.ModelAdmin):
    list_display = ['client', 'type', 'id']


admin.site.register(QuestradeAccount, AccountAdmin)


class ClientAdmin(admin.ModelAdmin):
    list_display = ['username']


admin.site.register(QuestradeClient, ClientAdmin)
