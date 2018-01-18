from django.conf.urls import url

from . import views

app_name = 'finance'
urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^portfolio/$', views.Portfolio, name='portfolio'),
    url(r'^history/(?P<period>[\w]+)/$', views.History, name='history'),
    url(r'^snapshot/$', views.SnapshotDetail.as_view(), name='snapshot'),
    url(r'^rebalance/$', views.RebalanceView.as_view(), name='rebalance'),
    url(r'^account/(?P<pk>[\w]+)/$', views.AccountDetail.as_view(), name='accountdetail'),
    url(r'^capgains/(?P<pk>.*)/$', views.CapGainsSecurityReport.as_view(), name='capgainssec'),
    url(r'^capgains/$', views.CapGainsReport.as_view(), name='capgains'),
    url(r'^security/(?P<symbol>.*)/$', views.securitydetail, name='securitydetail'),
    url(r'^uploadcsv/$', views.AccountCsvUpload.as_view(), name='uploadcsv'),
    url(r'^feedback/$', views.FeedbackView.as_view(), name='feedback'),
    url(r'^dividends/$', views.DividendReport.as_view(), name='dividends'),

    url(r'^user/(?P<pk>\d+)$', views.UserProfileView.as_view(), name='userprofile'),
    url(r'^user/(?P<pk>\d+)/password$', views.UserPasswordPost.as_view(), name='passwordchange'),

    # Admin panels
    url(r'^admin/security/$', views.AdminSecurity.as_view(), name='admin_security'),
    url(r'^admin/accounts/$', views.AdminAccounts.as_view(), name='admin_accounts'),
    url(r'^admin/users/$', views.AdminUsers.as_view(), name='admin_users'),
]
