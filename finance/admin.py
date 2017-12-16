from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import BaseAccount, BaseClient, ManualRawActivity
from .models import Activity, Holding, Allocation
from .models import UserProfile

def MakeNormalizedFloat(field, desc):
    def display(self, obj, field=field):
        return getattr(obj, field).normalize()
    display.short_description = desc
    display.admin_order_field = field
    return display


class ManualRawActivityAdmin(admin.ModelAdmin):
    list_display = ['account', 'day', 'type', 'symbol', 'qty', 'price', 'currency', 'netAmount']
    list_filter = ['account', 'day', 'symbol', 'type']


admin.site.register(ManualRawActivity, ManualRawActivityAdmin)


class ActivityAdmin(admin.ModelAdmin):
    display_qty = MakeNormalizedFloat('qty', 'Quantity')
    display_price = MakeNormalizedFloat('price', 'Price')

    list_display = ['account', 'tradeDate', 'type', 'security',
                    'display_qty', 'display_price', 'cash', 'netAmount']
    list_filter = ['account', 'tradeDate', ('security', admin.RelatedOnlyFieldListFilter),
                   'type', ('cash', admin.RelatedOnlyFieldListFilter)]
    search_fields = ['description']


admin.site.register(Activity, ActivityAdmin)


class HoldingAdmin(admin.ModelAdmin):
    display_qty = MakeNormalizedFloat('qty', 'Quantity')
    list_display = ['account', 'security', 'display_qty', 'startdate', 'enddate']
    list_filter = ['account', 'security', 'enddate']


admin.site.register(Holding, HoldingAdmin)

admin.site.register(BaseAccount)
admin.site.register(BaseClient)


class AllocationAdmin(admin.ModelAdmin):
    list_display = ['user', 'desired_pct', 'list_securities']


admin.site.register(Allocation, AllocationAdmin)


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'User Profile'


class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline, )


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
