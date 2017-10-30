from django.contrib import admin

from .models import BaseRawActivity, BaseAccount, BaseClient


admin.site.register(BaseRawActivity)
admin.site.register(BaseAccount)
admin.site.register(BaseClient)