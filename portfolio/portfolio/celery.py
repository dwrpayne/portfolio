import os
from celery import Celery
from celery.schedules import crontab

# set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio.settings')

app = Celery('portfolio')

CELERY_IMPORTS=("")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print('Request: {0!r}'.format(self.request))

app.conf.beat_schedule = {
    'sync-daily-prices': {
        'task': 'finance.tasks.UpdateDailyPrices',
        'schedule': crontab(minute=0, hour=2),
    },
    'refresh-questrade-tokens': {
        'task': 'questrade.tasks.RefreshAccessTokens',
        'schedule': 10*60, # Every 10 minutes
    },
    'sync-live-prices': {
        'task': 'finance.tasks.LiveUpdateTask',
        'schedule': 30, # Every 30 seconds
    },
}
