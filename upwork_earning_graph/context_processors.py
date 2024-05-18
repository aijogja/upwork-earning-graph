from django.conf import settings


def general(request):
    data = {"title": "Earning Graph", "analytics_script": settings.ANALYTICS_SCRIPT}
    if "upwork_auth" in request.session:
        data["upwork_auth"] = request.session["upwork_auth"]

    return data
