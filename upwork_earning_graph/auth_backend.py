from django.contrib.auth.models import User


class CustomBackend:
    def authenticate(self, request, upwork_id=None):
        try:
            user = User.objects.get(username=upwork_id)
        except User.DoesNotExist:
            return None
        return user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
