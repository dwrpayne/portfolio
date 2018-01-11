from django.contrib import admin

from .models import VirtBrokersClient, VirtBrokersAccount, VirtBrokersRawActivity

admin.site.register(VirtBrokersClient)

admin.site.register(VirtBrokersRawActivity)

class VirtBrokersAccountAdmin(admin.ModelAdmin):
    list_display = ['client', 'type', 'id']

admin.site.register(VirtBrokersAccount, VirtBrokersAccountAdmin)

