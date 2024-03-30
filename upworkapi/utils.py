from django.conf import settings
import upwork
import random


class UpworkClient:
    client = None

    def __init__(self):
        self.get_client()

    def get_client(self):
        config = upwork.Config({
            'client_id': settings.UPWORK_PUBLIC_KEY,
            'client_secret': settings.UPWORK_SECRET_KEY,
            'redirect_uri': settings.UPWORK_CALLBACK_URL
        })
        self.client = upwork.Client(
            config
        )
        return self.client

    def get_authenticated_client(self, token):
        config = upwork.Config({
            'client_id': settings.UPWORK_PUBLIC_KEY,
            'client_secret': settings.UPWORK_SECRET_KEY,
            'token': token
        })
        client = upwork.Client(
            config
        )
        return client


upwork_client = UpworkClient()
