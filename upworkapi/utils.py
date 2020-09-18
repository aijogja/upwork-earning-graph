from django.conf import settings
import upwork
import random


class UpworkClient:
    client = None

    def __init__(self):
        self.get_client()

    def get_client(self):
        config = upwork.Config({
            'consumer_key': settings.UPWORK_PUBLIC_KEY,
            'consumer_secret': settings.UPWORK_SECRET_KEY
        })
        self.client = upwork.Client(
            config
        )
        return self.client

    def get_authenticated_client(
            self, oauth_access_token, oauth_access_token_secret):
        config = upwork.Config({
            'consumer_key': settings.UPWORK_PUBLIC_KEY,
            'consumer_secret': settings.UPWORK_SECRET_KEY,
            'access_token': oauth_access_token,
            'access_token_secret': oauth_access_token_secret
        })
        client = upwork.Client(
            config
        )
        return client


upwork_client = UpworkClient()
