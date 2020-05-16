from django.shortcuts import render, redirect
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from upworkapi.utils import upwork_client
import upwork

# Create your views here.


def auth(request):
    client = upwork_client.get_client()
    return redirect(client.auth.get_authorize_url())


def callback(request):
    data = {}
    client = upwork.Client(
        settings.UPWORK_PUBLIC_KEY,
        settings.UPWORK_SECRET_KEY
    )
    if request.method == 'GET' and request.GET.get('oauth_verifier'):
        verifier = request.GET.get('oauth_verifier')
        client.auth.get_authorize_url()
        oauth_token, oauth_token_secret = client.auth.get_access_token(
            verifier
        )

        client = upwork_client.get_authenticated_client(
            oauth_token, oauth_token_secret
        )
        user_info = client.auth.get_info()

        user, created = User.objects.get_or_create(
            username=user_info['info']['ref'],
            first_name=user_info['auth_user']['first_name'],
            last_name=user_info['auth_user']['last_name']
        )

        auth_user = authenticate(upwork_id=user.username)
        if auth_user:
            login(request, auth_user)
            upwork_auth = {
                'fullname': '{first_name} {last_name}'.format(
                    first_name=user_info['auth_user']['first_name'],
                    last_name=user_info['auth_user']['last_name'],
                    ),
                'profile_url': user_info['info']['profile_url'],
                'profile_picture': user_info['info']['portrait_50_img'],
                'oauth_access_token': oauth_token,
                'oauth_access_token_secret': oauth_token_secret
            }
            request.session['upwork_auth'] = upwork_auth
            messages.success(request, "Authentication Success.")
            return redirect('earning_graph')
        else:
            messages.warning(request, "Authentication Failed.")
            return redirect('home')
    else:
        return redirect('home')


def disconnect(request):
    if 'upwork_auth' in request.session:
        del request.session['upwork_auth']
        logout(request)
        messages.success(request, "Disconnect Success.")
    return redirect('home')
