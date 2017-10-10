from collections import defaultdict
import sys
import os
import math
sys.path.append(os.path.join(__file__,'..'))
from utils import strdate
import arrow
import pickle

from pandas_datareader import data as pdr
import fix_yahoo_finance as fyf
fyf.pdr_override()

class Prices:
    def __init__(self):
        self.dateToPriceMap = {}
        self.startDate = None
        self.endDate = None

    def Update(self, prices, start_date, end_date):
        self.dateToPriceMap.update(prices)
        self.startDate = start_date
        self.endDate = end_date

    def IsSynced(self, start_date, end_date):
        if arrow.get(start_date) < arrow.get(self.startDate): return False
        if arrow.get(end_date) > arrow.get(self.endDate): return False
        return True

    def GetPrice(self, date):
        for tries in range(10):
            if date in self.dateToPriceMap and not math.isnan(self.dateToPriceMap[date]) and self.dateToPriceMap[date] > 0.001:
                return self.dateToPriceMap[date]
            date = strdate(arrow.get(date).shift(days=-1))
        return 0

class DataProvider:
    DATA_FILE = os.path.join(os.path.dirname(__file__), 'private', 'datastore.pkl')
    EXCH_RATES_SYMBOL = {'USD' : 'DEXCAUS'}

    def __init__(self):
        self.prices = defaultdict(Prices)

    @classmethod
    def Create(cls):
        try:
            if os.path.exists(cls.DATA_FILE):
                with open(cls.DATA_FILE, 'rb') as f:
                    return pickle.load(f)
        except Exception as e:
            print (e)
        return DataProvider()

    def SaveToFile(self):
        with open(self.DATA_FILE, "wb") as f:
            pickle.dump(self, f)

    def SyncData(self, symbol, data_source, col_index, start_date, end_date):
        if self.prices[symbol].IsSynced(start_date, end_date):
            return
        for retry in range(5):
            try:
                print('Syncing prices for {} from {} to {}...'.format(symbol, start_date, end_date), end='')
                df = pdr.DataReader(symbol, data_source, start_date, end_date)
                values = {strdate(time) : price for time, price in zip(df.index, df[col_index])}
                self.prices[symbol].Update(values, start_date, end_date)
                print('DONE!')
                self.SaveToFile()
                break
            except Exception as e:
                print (e)
                print ('Failed, retrying!')
                pass    
            
    def SyncPrices(self, symbol, start_date, end_date = strdate(arrow.now())):
        # Hack to remap
        if symbol == 'DLR.U.TO': symbol = 'DLR-U.TO'
        self.SyncData(symbol, 'yahoo', 'Close', start_date, end_date)

    def SyncExchangeRates(self, symbol, start_date, end_date = strdate(arrow.now())):
        fred_lookup = self.EXCH_RATES_SYMBOL[symbol]
        self.SyncData(fred_lookup, 'fred', fred_lookup, start_date, end_date)

    def GetPrice(self, symbol, date):
        if symbol == 'DLR.U.TO': return 10
        assert symbol in self.prices, "You didn't sync prices for {}".format(symbol)            
        return self.prices[symbol].GetPrice(date)
    
    def GetExchangeRate(self, symbol, date):
        if symbol == 'CAD': return 1
        return self.GetPrice(self.EXCH_RATES_SYMBOL[symbol], date)

            

#if __name__=="__main__":
#    pr = YahooPriceReader()
#    pr.SyncPrices('TSLA', '2016-01-01','2017-01-01')
#    pr.GetClosingPrice('TSLA', '2016-04-04')