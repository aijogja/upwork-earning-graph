import time

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from oauthlib.oauth2 import InvalidGrantError, MissingTokenError
from requests_oauthlib import OAuth2Session


class UpworkTokenRefreshMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/static/"):
            return self.get_response(request)

        if request.path.startswith("/auth") or request.path.startswith("/callback"):
            return self.get_response(request)

        token = request.session.get("token")
        if not isinstance(token, dict):
            return self.get_response(request)

        _ensure_expires_at(token)
        if _needs_refresh(token):
            try:
                refreshed = _refresh_token(token)
                request.session["token"] = refreshed
                access_token = refreshed.get("access_token") or refreshed.get("token")
                if access_token:
                    request.session["access_token"] = access_token
            except (InvalidGrantError, MissingTokenError):
                _clear_token_session(request)
                messages.warning(
                    request, "Session expired. Please login again to continue."
                )
                return redirect("auth")

        return self.get_response(request)


def _ensure_expires_at(token):
    if "expires_at" in token:
        return
    expires_in = token.get("expires_in")
    if expires_in is None:
        return
    try:
        token["expires_at"] = time.time() + int(expires_in)
    except (TypeError, ValueError):
        return


def _needs_refresh(token, leeway_seconds=120):
    expires_at = token.get("expires_at")
    if not expires_at:
        return False
    try:
        return time.time() >= float(expires_at) - leeway_seconds
    except (TypeError, ValueError):
        return False


def _refresh_token(token):
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise MissingTokenError(description="Missing refresh token.")
    session = OAuth2Session(settings.UPWORK_PUBLIC_KEY, token=token)
    return session.refresh_token(
        "https://www.upwork.com/api/v3/oauth2/token",
        refresh_token=refresh_token,
        client_id=settings.UPWORK_PUBLIC_KEY,
        client_secret=settings.UPWORK_SECRET_KEY,
    )


def _clear_token_session(request):
    for key in ("token", "access_token", "tenant_id", "tenant_ids", "tenant_names"):
        if key in request.session:
            del request.session[key]
