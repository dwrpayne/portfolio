from .base import *

DEBUG = False
ALLOWED_HOSTS = ['.davidpayne.net', 'localhost']

LOGGING['loggers']['django']['handlers'] += ['file']
