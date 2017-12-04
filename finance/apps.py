from django.apps import AppConfig
import os
import plotly
import ctypes

class financeConfig(AppConfig):
    name = 'finance'
    
    def ready(self):
        plotly.tools.set_credentials_file(username=os.environ.get('PLOTLY_USERNAME'), api_key=os.environ.get('PLOTLY_API_KEY'))
        
        buf = ctypes.create_unicode_buffer(1024)
        ctypes.windll.kernel32.GetConsoleTitleW(ctypes.byref(buf), 1024)
        words = ' '.join(word for word in buf.value.split() if not word.isdigit())
        ctypes.windll.kernel32.SetConsoleTitleW('{} {}'.format(words, os.getpid()))