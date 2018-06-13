# Portfolio Tool

This is an investment portfolio analysis tool that syncs transaction history from multiple brokerages and provides a unified overall portfolio view. It also provides historical valuation data and charts based on historical stock prices and exchange rates, which are also automatically synced from several freely available sources.

# Feature set
* Current day's dashboard (think Google Finance clone).
* Historical dashboards (think Google Finance clone but I can see what it looked like on any day in history).
* Historical transaction history, slicable by stock, by account, or all on a timeline.
* Historical price charts for each stock, with buy/sell flags indicating transactions.
* Automatic rebalancing suggestions based on a user-defined desired target asset allocation.
* Automatic capital gains calculations based on current (2018) Canada Revenue Agency rules.
* Dividend graphs
* Updates stock prices every 5 minutes, transactions daily.

It's purpose built for the Canadian investor, and maintains the Canadian dollar value of each transaction as of the transaction date. This means capital gains and rate of return calculations correctly handle exchange rate fluctuations, which no other tool does that I could find.

It’s not yet ready for public consumption, but please contact me for access to the public demo if you want to see it in action.

## Activity Syncing

### Supported integrations

* [Questrade](http://www.questrade.com/) (automatic)
* [Tangerine](https://www.tangerine.ca) (automatic)
* [Great West Life GRS](https://ssl.grsaccess.com/public/en/home.aspx) (automatic)
* [Virtual Brokers](https://www.virtualbrokers.com) (via manual CSV upload)
* [RBC](https://www.rbcroyalbank.com) (via manual CSV upload)

### Supported data sources

This tools syncs exchange rate and price history for stocks and mutual funds from the following sources:

* OpenExchangeRates
* AlphaVantage
* Morningstar
* Yahoo Finance
* The Bank of Canada
* Questrade (options only)

