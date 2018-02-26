import json
import requests
from datetime import timedelta
import pandas


def get_data_from_sources(sources, start, end):
    """
    Gets data from all sources for the specified range and merges them by priority.
    Returns an iterator of (date, price) tuples
    """
    start = start - timedelta(days=7)

    index = pandas.DatetimeIndex(start=start, end=end, freq='D').date
    merged_series = pandas.Series(index=index, dtype='float64')

    for source in sources.order_by('priority'):
        print("Getting data from {} for {} to {}".format(source, start, end))
        data = source._Retrieve(start, end)
        merged_series.update(pandas.Series(dict(data)))

    merged_series = merged_series.reindex(index).fillna(method='ffill').fillna(method='bfill').sort_index()
    return merged_series.iteritems()


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

