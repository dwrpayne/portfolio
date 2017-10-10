import questrade
from utils import *

david = questrade.Client('David')
david.SyncAccounts()
david.SyncAccountBalances()
sarah = questrade.Client('Sarah')
sarah.SyncAccounts()
sarah.SyncAccountBalances()
david.PrintCombinedBalances()
sarah.PrintCombinedBalances()
print ('=====================')
total_sod = sum(map(questrade.Account.GetTotalSod, david.accounts+sarah.accounts))
total_now = sum(map(questrade.Account.GetTotalCAD, david.accounts+sarah.accounts))
print ('Total: {} -> {} ({})'.format(as_currency(total_sod), as_currency(total_now), as_currency(total_now-total_sod)))

david.SyncAccountPositions()
sarah.SyncAccountPositions()
positions = david.GetPositions() + sarah.GetPositions()
for symbol in set([p.symbol for p in positions]):
    print(sum([p for p in positions if p.symbol==symbol]))

