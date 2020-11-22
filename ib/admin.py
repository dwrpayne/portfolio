from django.contrib import admin

from .models import IbAccount, IbRawActivity

admin.site.register(IbRawActivity)

class IbAccountAdmin(admin.ModelAdmin):
    list_display = ['user', 'type', 'id']


admin.site.register(IbAccount, IbAccountAdmin)

