from django.urls import path

from . import views

app_name = 'charts'
urlpatterns = [
    path('growth/', views.GrowthChart, name='growth'),
]
