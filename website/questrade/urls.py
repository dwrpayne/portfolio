from django.conf.urls import url

from . import views

app_name = 'questrade'
urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^go$', views.analyze, name='analyze'),
    url(r'^historynew$', views.historynew, name='historynew'),
    url(r'^balances$', views.balances, name='balances'),
]