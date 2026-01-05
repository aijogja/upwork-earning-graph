from django.http import JsonResponse


def session_dump(request):
    return JsonResponse(
        {
            "has_token": "token" in request.session,
            "token_keys": list((request.session.get("token") or {}).keys()),
            "has_upwork_auth": "upwork_auth" in request.session,
            "upwork_auth": request.session.get("upwork_auth"),
            "is_authenticated": request.user.is_authenticated,
            "user": getattr(request.user, "username", None),
        }
    )
