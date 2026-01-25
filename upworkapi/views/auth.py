from urllib.parse import urlparse
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError, MissingTokenError
from upwork.routers import graphql
from django.shortcuts import render, redirect
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from upworkapi.utils import upwork_client
import traceback
from django.http import HttpResponse, HttpResponseBadRequest
import json
from upworkapi.services.tenant import get_tenant_id, list_tenants
import logging


# Create your views here.

logger = logging.getLogger(__name__)


def auth_view(request):
    client = upwork_client.get_client()
    authorization_url, state = client.get_authorization_url()
    request.session["upwork_oauth_state"] = state
    return redirect(authorization_url)


def callback(request):
    code = request.GET.get("code")
    state = request.GET.get("state")

    if request.method != "GET" or not code:
        return HttpResponseBadRequest("Missing ?code. Start from /auth")

    expected = request.session.get("upwork_oauth_state")
    if expected and state != expected:
        return HttpResponseBadRequest("OAuth state mismatch")

    client = upwork_client.get_client()
    authz_code = request.build_absolute_uri()

    data = None  # <-- kunci: selalu terdefinisi

    try:
        token = client.get_access_token(authz_code)
        request.session["token"] = token

        access_token = _extract_access_token(token, client)
        if not access_token:
            raise Exception("access_token not found")

        request.session["access_token"] = access_token

        tenant_items = list_tenants(access_token)
        if tenant_items:
            request.session["tenant_ids"] = [
                str(t.get("organizationId"))
                for t in tenant_items
                if t.get("organizationId")
            ]
            request.session["tenant_names"] = [
                t.get("title") or "" for t in tenant_items
            ]

        tenant_id = get_tenant_id(access_token)
        if tenant_id:
            request.session["tenant_id"] = tenant_id

        query = """
        query {
            user {
                rid
                email
                photoUrl
                freelancerProfile {
                    fullName
                    firstName
                    lastName
                    personalData { profileUrl }
                }
            }
        }
        """

        data = graphql.Api(client).execute({"query": query})

        # Kalau GraphQL gagal, tampilkan response mentah
        if (
            not isinstance(data, dict)
            or "data" not in data
            or not data["data"]
            or not data["data"].get("user")
        ):
            return HttpResponse(
                "GraphQL user query failed:\n\n" + json.dumps(data, indent=2),
                status=500,
                content_type="text/plain",
            )

        user_data = data["data"]["user"]

        user, _ = User.objects.update_or_create(
            username=user_data["rid"],
            defaults={
                "email": user_data.get("email", ""),
                "first_name": user_data["freelancerProfile"].get("firstName", ""),
                "last_name": user_data["freelancerProfile"].get("lastName", ""),
            },
        )

        auth_user = authenticate(upwork_id=user.username)
        if not auth_user:
            return HttpResponse(
                "authenticate(upwork_id=...) returned None.\n"
                "Fix AUTHENTICATION_BACKENDS.\n"
                f"username={user.username}\n",
                status=500,
                content_type="text/plain",
            )

        login(request, auth_user)

        profile_url = user_data["freelancerProfile"]["personalData"].get("profileUrl")
        request.session["upwork_auth"] = {
            "fullname": user_data["freelancerProfile"].get("fullName", ""),
            "profile_picture": user_data.get("photoUrl"),
            "profile_url": profile_url,
        }
        profile_key = _extract_profile_key(profile_url)
        if profile_key:
            request.session["freelancer_reference"] = profile_key

        messages.success(request, "Authentication Success.")
        return redirect("earning_graph")

    except MissingTokenError:
        logger.exception(
            "OAuth callback missing token. code_present=%s state_present=%s state_match=%s",
            bool(code),
            bool(state),
            bool(expected and state == expected),
        )
        raise
    except InvalidGrantError as e:
        logger.exception(
            "OAuth callback invalid grant. code_present=%s state_present=%s state_match=%s",
            bool(code),
            bool(state),
            bool(expected and state == expected),
        )
        return HttpResponse(
            "InvalidGrantError:\n\n" + repr(e) + "\n\n" + traceback.format_exc(),
            status=400,
            content_type="text/plain",
        )
    except Exception as e:
        logger.exception(
            "OAuth callback exception. code_present=%s state_present=%s state_match=%s",
            bool(code),
            bool(state),
            bool(expected and state == expected),
        )
        extra = ""
        if data is not None:
            extra = "\n\nGraphQL response:\n" + json.dumps(data, indent=2)
        return HttpResponse(
            "Callback exception:\n\n"
            + repr(e)
            + "\n\n"
            + traceback.format_exc()
            + extra,
            status=500,
            content_type="text/plain",
        )


def disconnect(request):
    if "upwork_auth" in request.session:
        del request.session["upwork_auth"]
        del request.session["token"]
        logout(request)
        messages.success(request, "Disconnect Success.")
    return redirect("home")


@login_required(login_url="/")
def tenant_select(request):
    access_token = request.session.get("access_token")
    if not access_token:
        messages.warning(request, "Missing access token. Please login again.")
        return redirect("auth")

    tenants = list_tenants(access_token)
    if tenants:
        request.session["tenant_ids"] = [
            str(t.get("organizationId")) for t in tenants if t.get("organizationId")
        ]
        request.session["tenant_names"] = [t.get("title") or "" for t in tenants]
    if request.method == "POST":
        org_id = request.POST.get("organization_id")
        if not org_id:
            messages.warning(request, "Please select a tenant.")
        else:
            request.session["tenant_id"] = str(org_id)
            selected = next(
                (t for t in tenants if str(t.get("organizationId")) == str(org_id)),
                None,
            )
            if selected:
                request.session["tenant_name"] = selected.get("title") or ""
            messages.success(request, "Tenant updated.")
            return redirect("earning_graph")

    return render(
        request,
        "upworkapi/tenant_select.html",
        {
            "page_title": "Select Tenant",
            "tenants": tenants,
            "current_tenant": request.session.get("tenant_id"),
        },
    )


def _extract_profile_key(profile_url):
    if not profile_url:
        return None
    s = str(profile_url)
    if "~" in s:
        return "~" + s.split("~", 1)[1].split("/", 1)[0]
    parts = [p for p in s.split("/") if p]
    if parts:
        last = parts[-1]
        if last.startswith("~"):
            return last
    return None


def _extract_access_token(token_obj, client_obj):
    # object style
    at = getattr(token_obj, "access_token", None)
    if at:
        return at

    # dict style
    if isinstance(token_obj, dict):
        at = token_obj.get("access_token") or token_obj.get("token")
        if at:
            return at

    # fallback: client.config.token
    cfg = getattr(client_obj, "config", None)
    tok = getattr(cfg, "token", None) if cfg else None
    if isinstance(tok, dict):
        return tok.get("access_token") or tok.get("token")

    return None
