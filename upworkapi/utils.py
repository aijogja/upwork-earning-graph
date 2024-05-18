from django.conf import settings
import upwork


class UpworkClient:
    client = None

    def __init__(self):
        self.get_client()

    def get_client(self, token=None):
        if token:
            config = upwork.Config(
                {
                    "client_id": settings.UPWORK_PUBLIC_KEY,
                    "client_secret": settings.UPWORK_SECRET_KEY,
                    "redirect_uri": settings.UPWORK_CALLBACK_URL,
                    "token": token,
                }
            )
        else:
            config = upwork.Config(
                {
                    "client_id": settings.UPWORK_PUBLIC_KEY,
                    "client_secret": settings.UPWORK_SECRET_KEY,
                    "redirect_uri": settings.UPWORK_CALLBACK_URL,
                }
            )
        self.client = upwork.Client(config)
        return self.client


upwork_client = UpworkClient()
