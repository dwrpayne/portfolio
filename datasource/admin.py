from django.contrib import admin

from .models import AlphaVantageCurrencySource, MorningstarDataSource, InterpolatedDataSource
from .models import ConstantDataSource, PandasDataSource, AlphaVantageStockSource


class ConstantDataSourceAdmin(admin.ModelAdmin):
    list_display = ['value']
admin.site.register(ConstantDataSource, ConstantDataSourceAdmin)

class PandasDataSourceAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'source', 'column']
admin.site.register(PandasDataSource, PandasDataSourceAdmin)

class AlphaVantageStockSourceAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'api_key']
admin.site.register(AlphaVantageStockSource, AlphaVantageStockSourceAdmin)

class AlphaVantageCurrencySourceAdmin(admin.ModelAdmin):
    list_display = ['from_symbol', 'to_symbol', 'api_key']
admin.site.register(AlphaVantageCurrencySource, AlphaVantageCurrencySourceAdmin)

class MorningstarDataSourceAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'raw_url']
admin.site.register(MorningstarDataSource, MorningstarDataSourceAdmin)

class InterpolatedDataSourceAdmin(admin.ModelAdmin):
    list_display = ['start_day', 'start_val', 'end_day', 'end_val']
admin.site.register(InterpolatedDataSource, InterpolatedDataSourceAdmin)


