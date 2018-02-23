from decimal import Decimal
import json
import requests
from django.conf import settings

# TODO: Yuck, this is really hacky and needs a refactor. I just need it working for now.
# TODO: Maybe a ManyToMany field to support multiple data sources per security?
# TODO: Or maybe a DataSource that aggregates data from multiple sources
def GetLiveAlphaVantageExchangeRate(symbol):
    params = {'function': 'CURRENCY_EXCHANGE_RATE', 'apikey': settings.ALPHAVANTAGE_KEY,
              'from_currency': symbol, 'to_currency': 'CAD'}
    r = requests.get('https://www.alphavantage.co/query', params=params)
    if r.ok:
        j = r.json()
        return Decimal(j['Realtime Currency Exchange Rate']['5. Exchange Rate'])
    else:
        print('Failed to get data, response: {}'.format(r.content))
    return None

def GetYahooStockData(symbol):
    print('Refreshing metadata for ' + symbol)
    req = requests.get('https://finance.yahoo.com/quote/' + symbol)
    text = req.text
    i1 = 0
    i1 = text.find('root.App.main', i1)
    i1 = text.find('{', i1)
    i2 = text.find("\n", i1)
    i2 = text.rfind(';', i1, i2)
    jsonstr = text[i1:i2]
    j = json.loads(jsonstr)
    for tag in ['context', 'dispatcher', 'stores', 'QuoteSummaryStore']:
        if not tag in j:
            print('Missing json tag {}, skipping...'.format(tag))
            return {}
        j = j[tag]
    return j

