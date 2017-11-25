import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio.settings')

# set the default Django settings module for the 'celery' program.

app = Celery('portfolio')

CELERY_IMPORTS=("")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

app.conf.timezone = 'Canada/Pacific'

@app.task(bind=True)
def debug_task(self):
    print('Request: {0!r}'.format(self.request))

app.conf.beat_schedule = {
    'sync-daily-client-prices': {
        'task': 'finance.tasks.DailyUpdateTask',
        'schedule': crontab(minute=0, hour=4),
    },
    'refresh-questrade-tokens': {
        'task': 'questrade.tasks.RefreshAccessTokens',
        'schedule': crontab(minute='*/15')
    },
    'sync-live-exchanges': {
        'task': 'finance.tasks.LiveExchangeUpdateTask',
        'schedule': crontab(minute='0', hour='*')
    },
    'sync-live-prices': {
        'task': 'finance.tasks.LiveSecurityUpdateTask',
        'schedule': crontab(minute='*', hour='6-15', day_of_week='mon-fri')
    },
}
