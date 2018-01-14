from django.apps import AppConfig


class DatasourceConfig(AppConfig):
    name = 'datasource'


    def ready(self):
        from . import signals

