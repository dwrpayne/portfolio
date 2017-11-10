from django.conf.urls import url

from . import views

app_name = 'finance'
urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^go$', views.analyze, name='analyze'),
    url(r'^history$', views.DoWorkHistory, name='history'),
    url(r'^account/(?P<account_id>.*)/$', views.accountdetail, name='accountdetail'),
    url(r'^security/(?P<symbol>.*)/$', views.securitydetail, name='securitydetail'),
]
