from django.test import TestCase

from .models import *

client = Client.objects.get(username='David')
client.Authorize()

class ClientModelTests(TestCase):
    def test_make_security(self):
        client.EnsureSecuritiesExist([38526])
        s = Security.objects.get(symbolid=38526)
        self.assertEqual(str(s.symbol), 'TSLA')

    def test_make_security_preexisting(self):
        client.EnsureSecuritiesExist([38526])
        client.EnsureSecuritiesExist([38526,8049])
        self.assertEqual(len(Security.objects.all()), 2)


class SecurityModelTests(TestCase):
    def hi(self):
        pass

class ActivityModelTests(TestCase):
    def test_create_from_json(self):
        json = {'tradeDate': '2013-07-29T00:00:00.000000-04:00', 'transactionDate': '2013-08-01T00:00:00.000000-04:00', 'settlementDate': '2013-08-01T00:00:00.000000-04:00', 'action': 'Buy', 'symbol': 'VTI', 'symbolId': 40571, 'description': 'VANGUARD INDEX FUNDS           VANGUARD TOTAL STOCK MARKET    ETF                            WE ACTED AS AGENT', 'currency': 'USD', 'quantity': 11, 'price': 87.12, 'grossAmount': -958.32, 'commission': 0, 'netAmount': -958.32, 'type': 'Trades'}
        Activity.CreateFromJson(json, c.account_set.all()[0])
        self.assertEqual(Activity.objects.all()[0].quantity,11)
        self.assertEqual(Activity.objects.all()[0].quantity,Decimal(87.12))