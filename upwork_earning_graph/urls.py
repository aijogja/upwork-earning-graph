"""upwork_earning_graph URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from .views import home, about, contact
from upworkapi.views import auth, reports

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'),
    path('about', about, name='about'),
    path('contact', contact, name='contact'),
    path('auth', auth.auth_view, name='auth'),
    path('callback', auth.callback, name='callback'),
    path('logout', auth.disconnect, name='logout'),
    path('earning', reports.earning_graph, name='earning_graph'),
    path('timereport', reports.timereport_graph, name='timereport_graph'),
]
