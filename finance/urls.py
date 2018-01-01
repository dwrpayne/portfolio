from django.conf.urls import url

from . import views

app_name = 'finance'
urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^portfolio/$', views.Portfolio, name='portfolio'),
    url(r'^history/(?P<period>[\w]+)/$', views.History, name='history'),
    url(r'^snapshot/$', views.SnapshotDetail.as_view(), name='snapshot'),
    url(r'^rebalance/$', views.Rebalance, name='rebalance'),
    url(r'^account/(?P<pk>[\w]+)/$', views.AccountDetail.as_view(), name='accountdetail'),
    url(r'^capgains/(?P<pk>.*)/$', views.CapGainsReport.as_view(), name='capgains'),
    url(r'^security/(?P<symbol>.*)/$', views.securitydetail, name='securitydetail'),
    url(r'^dividends/$', views.DividendReport.as_view(), name='dividends'),
]
