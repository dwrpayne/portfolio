from urllib.parse import urlencode, quote
from . import exceptions
from .login import TangerineLoginFlow
import functools
import datetime
import contextlib
import requests
import logging
from utils.api import api_response

logger = logging.getLogger(__name__)

DEFAULT_LOCALE = 'en_CA'


class TangerineClient(object):
    def __init__(self, secret_provider, session=None, locale=DEFAULT_LOCALE):
        if session is None:
            session = requests.Session()
        self.session = session
        self.login_flow = TangerineLoginFlow(secret_provider, self.session, locale)

    def _api_get(self, path):
        url = 'https://secure.tangerine.ca/web/rest{}'.format(path)
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

    @contextlib.contextmanager
    def login(self):
        self.login_flow.start()
        try:
            yield
        except Exception:
            raise
        finally:
            self.login_flow.end()

    @api_response('customer')
    def me(self):
        return self._api_get('/v1/customers/my')

    @api_response('accounts')
    def list_accounts(self):
        return self._api_get('/pfm/v1/accounts')

    @api_response('account_summary')
    def get_account(self, account_id: str):
        return self._api_get('/v1/accounts/{}?billing-cycle-ranges=true'.format(account_id))

    @api_response('transactions')
    def list_transactions(self, account_ids: list, period_from: datetime.date, period_to: datetime.date):
        params = {
            'accountIdentifiers': ','.join(account_ids),
            'hideAuthorizedStatus': True,
            'periodFrom': period_from.strftime('%Y-%m-%dT00:00:00.000Z'),
            'periodTo': period_to.strftime('%Y-%m-%dT00:00:00.000Z'),
            'skip': 0,
        }
        return self._api_get('/pfm/v1/transactions?{}'.format(urlencode(params)))

    @api_response('token', check_response_status=False)
    def _get_transaction_download_token(self):
        return self._api_get('/v1/customers/my/security/transaction-download-token')

    def download_ofx(self, account, start_date: datetime.date, end_date: datetime.date):
        if account['type'] == 'CHEQUING':
            account_type = 'SAVINGS'
            account_display_name = account['display_name']
            account_nickname = account['nickname']
        elif account['type'] == 'SAVINGS':
            account_type = 'SAVINGS'
            account_display_name = account['display_name']
            account_nickname = account['nickname']
        elif account['type'] == 'CREDIT_CARD':
            account_type = 'CREDITLINE'
            account_details = self.get_account(account['number'])
            account_display_name = account_details['display_name']
            account_nickname = account_details['account_nick_name']
        else:
            raise exceptions.UnsupportedAccountTypeForDownload(account['type'])

        token = self._get_transaction_download_token()
        filename = '{}.QFX'.format(account_nickname)
        params = {
            'fileType': 'QFX',
            'ofxVersion': '102',
            'sessionId': 'tng',
            'orgName': 'Tangerine',
            'bankId': '0614',
            'language': 'eng',
            'acctType': account_type,
            'acctNum': account_display_name,
            'acctName': account_nickname,
            'userDefined': token,
            'startDate': start_date.strftime('%Y%m%d'),
            'endDate': end_date.strftime('%Y%m%d'),
            'orgId': 10951,
            'custom.tag': 'customValue',
            'csvheader': 'Date,Transaction,Name,Memo,Amount',
        }
        response = self.session.get('https://ofx.tangerine.ca/{}?{}'.format(quote(filename), urlencode(params)),
                                    headers={'Referer': 'https://www.tangerine.ca/app/'})
        response.raise_for_status()
        local_filename = '{}_{}-{}.QFX'.format(account_nickname,
                                               start_date.strftime('%Y%m%d'),
                                               end_date.strftime('%Y%m%d'))
        with open(local_filename, 'w') as f:
            f.write(response.text)

        logger.info('Saved: {}'.format(local_filename))
        return local_filename
