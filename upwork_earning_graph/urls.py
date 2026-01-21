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
from upworkapi.views import auth, reports, debug


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", home, name="home"),
    path("about/", about, name="about"),
    path("contact/", contact, name="contact"),
    path("auth/", auth.auth_view, name="auth"),
    path("callback/", auth.callback, name="callback"),
    path("logout/", auth.disconnect, name="logout"),
    path("earning/", reports.earning_graph, name="earning_graph"),
    path("earning/total/", reports.total_earning_graph, name="total_earning_graph"),
    path(
        "earning/total/<int:year>",
        reports.total_earning_graph,
        name="total_earning_graph_year",
    ),
    path(
        "earning/all-time/",
        reports.all_time_earning_graph,
        name="all_time_earning_graph",
    ),
    path(
        "earning/all-time/<int:year>",
        reports.all_time_earning_year,
        name="all_time_earning_year",
    ),
    path(
        "earning/all-time/<int:year>/<int:month>",
        reports.all_time_earning_month,
        name="all_time_earning_month",
    ),
    path("timereport/", reports.timereport_graph, name="timereport_graph"),
    path(
        "earning/<int:year>/<int:month>/client/<str:client_name>/",
        reports.earning_month_client_detail,
        name="earning_month_client_detail",
    ),
    path("debug/session/", debug.session_dump),
    path("earning/fixed/", reports.fixed_price_graph, name="fixed_price_graph"),
    path(
        "earning/fixed/<int:year>/<int:month>",
        reports.fixed_price_month_detail,
        name="fixed_price_month_detail",
    ),
]
