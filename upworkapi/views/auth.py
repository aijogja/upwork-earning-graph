from urllib.parse import urlparse
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError
from upwork.routers import graphql
from django.shortcuts import render, redirect
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from upworkapi.utils import upwork_client
import traceback
from django.http import HttpResponse, HttpResponseBadRequest
import json




# Create your views here.


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
        if not isinstance(data, dict) or "data" not in data or not data["data"] or not data["data"].get("user"):
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

        request.session["upwork_auth"] = {
            "fullname": user_data["freelancerProfile"].get("fullName", ""),
            "profile_picture": user_data.get("photoUrl"),
            "profile_url": user_data["freelancerProfile"]["personalData"].get("profileUrl"),
        }

        messages.success(request, "Authentication Success.")
        return redirect("earning_graph")

    except InvalidGrantError as e:
        return HttpResponse(
            "InvalidGrantError:\n\n" + repr(e) + "\n\n" + traceback.format_exc(),
            status=400,
            content_type="text/plain",
        )
    except Exception as e:
        extra = ""
        if data is not None:
            extra = "\n\nGraphQL response:\n" + json.dumps(data, indent=2)
        return HttpResponse(
            "Callback exception:\n\n" + repr(e) + "\n\n" + traceback.format_exc() + extra,
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