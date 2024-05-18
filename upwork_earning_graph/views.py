from django.shortcuts import render
from django.contrib import messages


# Create your views here.


def home(request):
    data = {"page_title": "Home"}
    return render(request, "index.html", data)


def about(request):
    data = {"page_title": "About"}
    return render(request, "about.html", data)


def contact(request):
    data = {"page_title": "Contact"}
    return render(request, "contact.html", data)
