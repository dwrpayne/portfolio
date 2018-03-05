from django.urls import path

from . import views

app_name = 'finance'
urlpatterns = [
    path('', views.index, name='index'),
    path('portfolio/', views.PortfolioView.as_view(), name='portfolio'),
    path('portfolio/<chart>/', views.PortfolioView.as_view(), name='portfolio1'),
    path('history/<period>/', views.HistoryDetail.as_view(), name='history'),
    path('snapshot/', views.SnapshotDetail.as_view(), name='snapshot'),
    path('rebalance/', views.RebalanceView.as_view(), name='rebalance'),
    path('account/<pk>/', views.AccountDetail.as_view(), name='accountdetail'),
    path('capgains/<pk>/', views.CapGainsSecurityReport.as_view(), name='capgainssec'),
    path('capgains/', views.CapGainsReport.as_view(), name='capgains'),
    path('security/<pk>/', views.SecurityDetail.as_view(), name='securitydetail'),
    path('uploadcsv/', views.AccountCsvUpload.as_view(), name='uploadcsv'),
    path('feedback/', views.FeedbackView.as_view(), name='feedback'),
    path('dividends/', views.DividendReport.as_view(), name='dividends'),

    # Profile
    path('user/<int:pk>/', views.UserProfileView.as_view(), name='userprofile'),
    path('user/<int:pk>/password/', views.UserPasswordPost.as_view(), name='passwordchange'),

    # Admin panels
    path('admin/security/', views.AdminSecurity.as_view(), name='admin_security'),
    path('admin/accounts/', views.AdminAccounts.as_view(), name='admin_accounts'),
    path('admin/users/', views.AdminUsers.as_view(), name='admin_users'),
]
