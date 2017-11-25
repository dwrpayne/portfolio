from django.conf.urls import url

from . import views

app_name = 'finance'
urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^portfolio$', views.Portfolio, name='portfolio'),
    url(r'^history$', views.History, name='history'),
    url(r'^rebalance', views.Rebalance, name='rebalance'),
    url(r'^account/(?P<account_id>.*)/$', views.accountdetail, name='accountdetail'),
    url(r'^security/(?P<symbol>.*)/$', views.securitydetail, name='securitydetail'),
]
