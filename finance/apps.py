from django.apps import AppConfig
import plotly
from django.conf import settings

class financeConfig(AppConfig):
    name = 'finance'
    
    def ready(self):
        plotly.tools.set_credentials_file(username=settings.PLOTLY_USERNAME, api_key=settings.PLOTLY_API_KEY)
