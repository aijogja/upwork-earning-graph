from urllib.parse import urlparse
from django.shortcuts import render, redirect
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from upworkapi.utils import upwork_client
from upwork.routers import auth

# Create your views here.


def auth_view(request):
    client = upwork_client.get_client()
    authorization_url, state = client.get_authorization_url()
    return redirect(authorization_url)


def callback(request):
    if request.method == 'GET' and request.GET.get('code'):
        client = upwork_client.client
        parsed_url = urlparse(request.get_raw_uri())
        authz_code = "%s?%s" % (settings.UPWORK_CALLBACK_URL, parsed_url.query)
        print(authz_code)
        token = client.get_access_token(authz_code)
        print(token)
        print(client.config.token)

        from upwork.routers import auth
        user = auth.Api(client).get_user_info()
        print(user)

        # from upwork.routers import graphql
        # query = """
        #     query {
        #     user {
        #         id
        #         nid
        #         rid
        #     }
        #     organization {
        #         id
        #     }}
        # """
        # print(query)
        # print(graphql.Api(client).execute({'query': query}))

        # client = upwork_client.get_authenticated_client(token)
        # user_info = auth.Api(client).get_user_info()
        # print(user_info)

        # user, created = User.objects.get_or_create(
        #     username=user_info['info']['ref'],
        #     first_name=user_info['auth_user']['first_name'],
        #     last_name=user_info['auth_user']['last_name']
        # )
        # if client.config.token:
        #     user = User.objects.get(username=5217226)
        #     print(user)

        # auth_user = authenticate(upwork_id=user.username)
        # if auth_user:
        #     login(request, auth_user)
        #     upwork_auth = {
        #         # 'fullname': '{first_name} {last_name}'.format(
        #         #     first_name=user_info['auth_user']['first_name'],
        #         #     last_name=user_info['auth_user']['last_name'],
        #         #     ),
        #         # 'profile_url': user_info['info']['profile_url'],
        #         # 'profile_picture': user_info['info']['portrait_50_img'],
        #         # 'access_token': access_token,
        #         # 'access_token_secret': access_token_secret
        #     }
        #     request.session['upwork_auth'] = upwork_auth
        #     messages.success(request, "Authentication Success.")
        #     return redirect('earning_graph')
        # # else:
        # #     messages.warning(request, "Authentication Failed.")
        # #     return redirect('home')
        return redirect('home')
    else:
        return redirect('home')


def disconnect(request):
    if 'upwork_auth' in request.session:
        del request.session['upwork_auth']
        logout(request)
        messages.success(request, "Disconnect Success.")
    return redirect('home')
