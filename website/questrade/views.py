from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse, StreamingHttpResponse

# Create your views here.
from .models import Client, Account, HackInitMyAccount, DataProvider, Holding
import arrow
import datetime
from utils import as_currency,  strdate


def SyncNewData(start):
    for client in Client.objects.all():
        c.Authorize()
        c.SyncAccounts()
        c.SyncAllActivitiesSlow(start)
        c.SyncPrices(start)
        c.UpdateMarketPrices()


def DoWork():
    yield "<html><body><pre>"
    yield "<br>Syncing Data..."

    data_provider = DataProvider('CAD')
    data_provider.SyncExchangeRates('USD')
    
    yield "<br>Processing accounts..."
    all_accounts = Account.objects.all()
    all_holdings = Holding.objects.filter(account__in=Account.objects.all(), enddate=None)

    yield '<br><br>Symbol\tPrice\t\t   Change\t\tShares\tGain<br>'
    total_gain = 0
    total_value = 0
    for symbol in all_holdings.values_list('symbol',flat=True).distinct():
        total_qty = sum(all_holdings.filter(symbol=symbol).values_list('qty', flat=True))

		# TODO: Hacky to get it working.
        yesterday_price = data_provider.GetPrice(symbol, datetime.date.today() - datetime.timedelta(days=7))
        today_price = data_provider.GetPrice(symbol, datetime.date.today())
        price_delta = today_price - yesterday_price
        this_gain = price_delta * total_qty * data_provider.GetExchangeRate('CAD' if '.TO' in symbol else 'USD', datetime.date.today())
        total_gain += this_gain
        total_value += total_qty * today_price * data_provider.GetExchangeRate('CAD' if '.TO' in symbol else 'USD', datetime.date.today())
        color = "green" if price_delta > 0 else "red"
        yield '{} \t{:.2f}\t\t<font color="{}">{:+.2f} ({:+.2%})</font>\t\t{:.0f}  \t{}<br>'.format(
            symbol.split('.')[0], today_price, color, price_delta, price_delta / yesterday_price, total_qty, as_currency(this_gain))
    yield '-------------------------------------<br>'
    
    color = "green" if total_gain > 0 else "red"
    yield 'Total: \t\t\t<font color="{}">{:+,.2f}({:+.2%})</font>\t{}<br>'.format(color, total_gain, total_gain / total_value, as_currency(total_value))
    yield '\nCurrent USD exchange: {:.4f}<br>'.format( 1/data_provider.GetExchangeRate('USD', datetime.date.today()))
    yield '</pre></body></html>'
    
def analyze(request):
    return StreamingHttpResponse(DoWork())

def DoWorkHistory():
    yield "<html><body><pre>"
    yield "<br>Syncing Data..."
    yield "<br>Processing history"
    all_accounts = Account.objects.all()[:1]
    #for a in all_accounts:
    #    a.RegenerateDBHoldings()
    #    yield "."
    yield "<br>"
    start = '2011-01-01'
    yield '<br>Date\t\t' + '\t'.join([a.client.username[0] + a.type for a in all_accounts]) + '\tTotal'
    for day in arrow.Arrow.range('day', arrow.get(start), arrow.now()):
        d = day.date()
        account_vals = [int(a.GetValueAtDate(d)) for a in all_accounts]
        yield '<br>{}\t'.format(d) + '\t'.join([str(val) for val in account_vals]) + '\t' + str(sum(account_vals))
    yield '</pre></body></html>'

def history(request):
    return StreamingHttpResponse(DoWorkHistory())  

def AccountBalances():
    yield "<html><body><pre>"
    yield "<br>Syncing Data..."
    yield "<br>Account\tSOD in CAD\tCurrent CAD"
    for c in Client.objects.all():
        c.Authorize()
        for a in c.account_set.all():
            json = c._GetRequest('accounts/%s/balances'%(a.account_id))            
            combinedCAD = next(currency['totalEquity'] for currency in json['combinedBalances'] if currency['currency'] == 'CAD')
            sodCombinedCAD = next(currency['totalEquity'] for currency in json['sodCombinedBalances'] if currency['currency'] == 'CAD')
            yield "<br>{} {}\t{:.2f}\t{:.2f}".format(a.client.username, a.type, sodCombinedCAD, combinedCAD)

def balances(request):    
    return StreamingHttpResponse(AccountBalances())  

def index(request):
    return HttpResponse("Hello world, you're at the questrade index.")