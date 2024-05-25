from django.conf import settings


def general(request):
    data = {
        "title": "Earning Graph",
        "google_analytics_id": settings.GOOGLE_ANALYTICS_ID,
    }
    if "upwork_auth" in request.session:
        data["upwork_auth"] = request.session["upwork_auth"]

    return data
