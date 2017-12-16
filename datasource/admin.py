from django.contrib import admin

from .models import DataSourceMixin, ConstantDataSource, PandasDataSource, AlphaVantageDataSource, \
    MorningstarDataSource, StartEndDataSource

class ConstantDataSourceAdmin(admin.ModelAdmin):
    list_display = ['value']
admin.site.register(ConstantDataSource, ConstantDataSourceAdmin)

class PandasDataSourceAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'source', 'column']
admin.site.register(PandasDataSource, PandasDataSourceAdmin)

class AlphaVantageDataSourceAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'function', 'api_key']
admin.site.register(AlphaVantageDataSource, AlphaVantageDataSourceAdmin)

class MorningstarDataSourceAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'raw_url']
admin.site.register(MorningstarDataSource, MorningstarDataSourceAdmin)

class StartEndDataSourceAdmin(admin.ModelAdmin):
    list_display = ['start_day', 'start_val', 'end_day', 'end_val']
admin.site.register(StartEndDataSource, StartEndDataSourceAdmin)


