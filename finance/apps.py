from django.apps import AppConfig
import os
import plotly

class financeConfig(AppConfig):
    name = 'finance'
    
    def ready(self):
        plotly.tools.set_credentials_file(username=os.environ.get('PLOTLY_USERNAME'), api_key=os.environ.get('PLOTLY_API_KEY'))
