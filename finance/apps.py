from django.apps import AppConfig

class financeConfig(AppConfig):
    name = 'finance'

    def ready(self):
        import finance.signals
