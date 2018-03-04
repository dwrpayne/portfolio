import json
from datetime import timedelta

import pandas
import requests


def get_data_from_sources(sources, start, end):
    """
    Gets data from all sources for the specified range and merges them by priority.
    Returns a pandas DataFrame
    """
    start = start - timedelta(days=7)

    index = pandas.DatetimeIndex(start=start, end=end, freq='D').date
    merged_frame = pandas.DataFrame(index=index, columns=['price', 'priority'], dtype='float64')

    for source in sources.order_by('priority'):
        print("Getting data from {} for {} to {}".format(source, start, end))
        data = source._Retrieve(start, end)
        if not isinstance(data, pandas.Series):
            data = pandas.Series(dict(data))
        data.name = 'price'
        frame = pandas.DataFrame(data)
        frame['priority'] = source.priority
        merged_frame.update(frame)

    merged_frame.update(merged_frame.price.fillna(method='ffill'))
    merged_frame.update(merged_frame.priority.fillna(0))

    return merged_frame.sort_index().dropna()


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

