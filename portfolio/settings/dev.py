from .base import *
from django.contrib.messages import constants as message_constants

DEBUG = True
DEBUG_TOOLBAR_ENABLED = True

if DEBUG_TOOLBAR_ENABLED:
    INSTALLED_APPS.append('debug_toolbar')
    MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')

MESSAGE_LEVEL = message_constants.DEBUG

CACHES['default']['KEY_PREFIX'] = 'devel'
CACHE_MIDDLEWARE_SECONDS = 1
