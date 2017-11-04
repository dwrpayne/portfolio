from django.conf.urls import url

from . import views

app_name = 'questrade'
urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^go$', views.analyze, name='analyze'),
    url(r'^history$', views.DoWorkHistory, name='history'),
]