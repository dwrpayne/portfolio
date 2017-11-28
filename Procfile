web: python manage.py runserver 0.0.0.0:$PORT
celery: celery worker -A portfolio -E -l INFO
celerybeat: celery -A portfolio beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler