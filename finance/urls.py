from django.conf.urls import url

from . import views

app_name = 'finance'
urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^portfolio/$', views.Portfolio, name='portfolio'),
    url(r'^history/(?P<period>[\w]+)/$', views.History, name='history'),
    url(r'^snapshot/$', views.Snapshot, name='snapshot'),
    url(r'^rebalance/$', views.Rebalance, name='rebalance'),
    url(r'^account/(?P<account_id>[\w]+)/$', views.accountdetail, name='accountdetail'),
    url(r'^capgains/(?P<symbol>.*)/$', views.capgains, name='capgains'),
    url(r'^security/(?P<symbol>.*)/$', views.securitydetail, name='securitydetail'),
]
