from django.contrib import admin


from .models import Client, Account, ExchangeRate, StockPrice

admin.site.register(Client)
admin.site.register(Account)
admin.site.register(ExchangeRate)
admin.site.register(StockPrice)