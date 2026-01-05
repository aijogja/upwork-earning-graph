from django.test import TestCase, Client, RequestFactory
from django.urls import reverse
from django.contrib.auth.models import User
from django.contrib.sessions.middleware import SessionMiddleware
from unittest.mock import patch, MagicMock
from upworkapi.views import auth


class AuthViewTestCase(TestCase):

    def setUp(self):
        self.client = Client()
        self.factory = RequestFactory()

    @patch("upworkapi.views.auth.upwork_client.get_client")
    def test_auth_view_redirects_to_authorization_url(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.get_authorization_url.return_value = (
            "https://upwork.com/oauth",
            "test_state",
        )
        mock_get_client.return_value = mock_client

        response = self.client.get(reverse("auth"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("https://upwork.com/oauth"))
        self.assertIn("upwork_oauth_state", self.client.session)

    def test_callback_without_code_returns_bad_request(self):
        response = self.client.get(reverse("callback"))
        self.assertEqual(response.status_code, 400)

    @patch("upworkapi.views.auth.upwork_client.get_client")
    def test_callback_with_state_mismatch(self, mock_get_client):
        session = self.client.session
        session["upwork_oauth_state"] = "expected_state"
        session.save()

        response = self.client.get(
            reverse("callback"), {"code": "test_code", "state": "wrong_state"}
        )
        self.assertEqual(response.status_code, 400)

    @patch("upworkapi.views.auth.login")
    @patch("upworkapi.views.auth.graphql.Api")
    @patch("upworkapi.views.auth.upwork_client.get_client")
    @patch("upworkapi.views.auth.authenticate")
    def test_callback_success_flow(
        self, mock_authenticate, mock_get_client, mock_graphql_api, mock_login
    ):
        session = self.client.session
        session["upwork_oauth_state"] = "test_state"
        session.save()

        mock_client = MagicMock()
        mock_client.get_access_token.return_value = {"access_token": "test_token"}
        mock_get_client.return_value = mock_client

        mock_api = MagicMock()
        mock_api.execute.return_value = {
            "data": {
                "user": {
                    "rid": "test_rid",
                    "email": "test@example.com",
                    "photoUrl": "https://example.com/photo.jpg",
                    "freelancerProfile": {
                        "fullName": "Test User",
                        "firstName": "Test",
                        "lastName": "User",
                        "personalData": {"profileUrl": "https://upwork.com/profile"},
                    },
                }
            }
        }
        mock_graphql_api.return_value = mock_api

        test_user = User.objects.create_user(
            username="test_rid", email="test@example.com"
        )
        mock_authenticate.return_value = test_user

        response = self.client.get(
            reverse("callback"), {"code": "test_code", "state": "test_state"}
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("earning_graph"))
        self.assertIn("token", self.client.session)
        self.assertIn("upwork_auth", self.client.session)

    def test_disconnect_clears_session_and_redirects(self):
        session = self.client.session
        session["upwork_auth"] = {"fullname": "Test User"}
        session["token"] = {"access_token": "test_token"}
        session.save()

        user = User.objects.create_user(username="testuser", password="testpass")
        self.client.force_login(user)

        response = self.client.get(reverse("logout"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))
        self.assertNotIn("upwork_auth", self.client.session)
        self.assertNotIn("token", self.client.session)

    def test_disconnect_without_session_redirects(self):
        response = self.client.get(reverse("logout"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))


class AuthURLTestCase(TestCase):

    def test_auth_url_resolves(self):
        url = reverse("auth")
        self.assertEqual(url, "/auth/")

    def test_callback_url_resolves(self):
        url = reverse("callback")
        self.assertEqual(url, "/callback/")

    def test_logout_url_resolves(self):
        url = reverse("logout")
        self.assertEqual(url, "/logout/")
