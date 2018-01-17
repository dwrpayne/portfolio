from django.contrib import admin

from .models import VirtBrokersAccount, VirtBrokersRawActivity


admin.site.register(VirtBrokersRawActivity)

class VirtBrokersAccountAdmin(admin.ModelAdmin):
    list_display = ['user', 'type', 'id']

admin.site.register(VirtBrokersAccount, VirtBrokersAccountAdmin)

