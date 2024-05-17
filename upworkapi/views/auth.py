from urllib.parse import urlparse
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError
from upwork.routers import graphql
from django.shortcuts import render, redirect
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from upworkapi.utils import upwork_client

# Create your views here.


def auth_view(request):
    client = upwork_client.get_client()
    authorization_url, state = client.get_authorization_url()
    return redirect(authorization_url)


def callback(request):
    if request.method == 'GET' and request.GET.get('code'):
        client = upwork_client.client
        parsed_url = urlparse(request.build_absolute_uri())
        authz_code = "%s?%s" % (settings.UPWORK_CALLBACK_URL, parsed_url.query)

        try:
            token = client.get_access_token(authz_code)
            request.session['token'] = token
            query = """
            query {
                user {
                    id
                    nid
                    rid
                    name
                    email
                    photoUrl
                    freelancerProfile {
                        fullName
                        firstName
                        lastName
                        personalData {
                            profileUrl
                        }
                    }
                }
            }
            """
            data = graphql.Api(client).execute({'query': query})
            if 'data' in data:
                list_name = data['data']['user']['name'].split(" ")
                user, created = User.objects.update_or_create(
                    username=data['data']['user']['rid'],
                    defaults={
                        'email': data['data']['user']['email'],
                        'first_name': data['data']['user']['freelancerProfile']['firstName'],
                        'last_name': data['data']['user']['freelancerProfile']['lastName']
                    }
                )
                auth_user = authenticate(upwork_id=user.username)
                if auth_user:
                    login(request, auth_user)
                    upwork_auth = {
                        'fullname': data['data']['user']['freelancerProfile']['fullName'],
                        'profile_picture': data['data']['user']['photoUrl'],
                        'profile_url': data['data']['user']['freelancerProfile']['personalData']['profileUrl'],
                    }
                    request.session['upwork_auth'] = upwork_auth
                    messages.success(request, "Authentication Success.")
                    return redirect('earning_graph')
            messages.warning(request, "Authentication Failed.")
            return redirect('home')
        except InvalidGrantError as e:
            messages.warning(request, "Authentication Failed.")
            return redirect('home')


def disconnect(request):
    if 'upwork_auth' in request.session:
        del request.session['upwork_auth']
        del request.session['token']
        logout(request)
        messages.success(request, "Disconnect Success.")
    return redirect('home')
