web: python manage.py runserver 0.0.0.0:$PORT
worker: celery.exe -A portfolio beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
worker: celery.exe worker -A portfolio -E -l INFO