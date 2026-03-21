from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing_page, name='index'),
    path('home/', views.home, name='home'),
    path("create-connection/", views.create_connection, name="create_connection"),
]