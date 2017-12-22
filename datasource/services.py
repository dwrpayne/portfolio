import requests
from decimal import Decimal
import json

# TODO: Yuck, this is really hacky and needs a refactor. I just need it working for now.
# TODO: Maybe a ManyToMany field to support multiple data sources per security?
# TODO: Or maybe a DataSource that aggregates data from multiple sources
def GetLiveAlphaVantageExchangeRate(symbol):
    params = {'function': 'CURRENCY_EXCHANGE_RATE', 'apikey': 'P38D2XH1GFHST85V',
              'from_currency': symbol, 'to_currency': 'CAD'}
    r = requests.get('https://www.alphavantage.co/query', params=params)
    if r.ok:
        json = r.json()
        return Decimal(json['Realtime Currency Exchange Rate']['5. Exchange Rate'])
    else:
        print('Failed to get data, response: {}'.format(r.content))
    return None

def GetYahooStockInformation(symbol):
    req = requests.get('https://finance.yahoo.com/quote/' + symbol)
    text = req.text
i1=0
i1=r.find('root.App.main', i1)
i1=r.find('{', i1)
i2=r.find("\n", i1)
i2=r.rfind(';', i1, i2)
jsonstr=r[i1:i2]
