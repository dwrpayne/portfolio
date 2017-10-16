from django.test import TestCase

from .models import *

class ClientModelTests(TestCase):

    def test_sync_david_accounts(self):
        c = Client.objects.get(username='david')
        c.Authorize()
        c.SyncAccounts()
        self.assertIs(len(c.accounts), 3)
        self.assertIn()
        for a in c.accounts: 
            HackInitMyAccount(a)
            if len(a.GetPositions()) > 0: 
                a.holdings[start] = Holdings(arrow.get(start), a.GetPositions(), a.currentHoldings.cashByCurrency)
    
        c.SyncAllActivitiesSlow(start)
        c.SyncPrices(start)
        #c.GenerateHoldingsHistory()
        c.UpdateMarketPrices()
        self.assertIs(future_question.was_published_recently(), False)