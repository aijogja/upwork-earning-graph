from django.conf import settings
import upwork
import random


class UpworkClient:
    client = None

    def __init__(self):
        self.get_client()

    def get_client(self):
        self.client = upwork.Client(
                settings.UPWORK_PUBLIC_KEY,
                settings.UPWORK_SECRET_KEY
            )
        return self.client

    def get_authenticated_client(
            self, oauth_access_token, oauth_access_token_secret):
        client = upwork.Client(
            settings.UPWORK_PUBLIC_KEY,
            settings.UPWORK_SECRET_KEY,
            oauth_access_token=oauth_access_token,
            oauth_access_token_secret=oauth_access_token_secret
        )
        return client


upwork_client = UpworkClient()
