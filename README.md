# Portfolio Tool

This is an investment portfolio analysis tool that syncs transaction history from several brokerages. It also provides historical valuation data and charts based on historical stock prices and exchange rates, which are also automatically synced from several freely available sources.

## Activity Syncing

### Supported integrations

* [Questrade](http://www.questrade.com/)
* [Tangerine](https://www.tangerine.ca)
* [Great West Life GRS](https://ssl.grsaccess.com/public/en/home.aspx)

###

It integrates with Questrade, Tangerine, and Great West GRS to provide automatic transaction syncing. It also integrates with Yahoo Finance (via pandas-datareader), Morningstar, AlphaVantage, OpenExchangeRates, and the Bank of Canada for syncing stock price and exchange rate historical data. 

I started it when Google announced in October that it was shutting down Google Finance portfolios, which I had been using. 

From just account activity and history price data, it then provides a dashboard of the current day’s price changes, displays historical portfolio values, historical stock price charts, recommends actions to maintain an asset allocation, and provides dividend and capital gains numbers for tax purposes.

It’s not yet ready for public consumption so I haven’t posted it on Github yet, 
