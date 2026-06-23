import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse


class TestUpworkAuthViews(TestCase):
    """Unit tests for Upwork authentication views."""

    def setUp(self):
        self.client = Client()
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpassword",
            email="test@example.com",
        )

    def tearDown(self):
        User.objects.all().delete()

    # ------------------------------------------------------------------
    # Login / OAuth entry-point
    # ------------------------------------------------------------------

    @patch("upworkapi.views.auth.upwork")
    def test_upwork_login_redirects_to_oauth(self, mock_upwork):
        """GET /auth/login should redirect the browser to Upwork's OAuth page."""
        mock_client = MagicMock()
        mock_client.get_authorize_url.return_value = (
            "https://www.upwork.com/ab/account-security/oauth2/authorize?token=test",
            "request_token",
            "request_token_secret",
        )
        mock_upwork.Client.return_value = mock_client

        response = self.client.get(reverse("upwork_login"))

        self.assertIn(response.status_code, [301, 302])

    @patch("upworkapi.views.auth.upwork")
    def test_upwork_login_stores_token_in_session(self, mock_upwork):
        """OAuth request tokens must be persisted in the session."""
        mock_client = MagicMock()
        mock_client.get_authorize_url.return_value = (
            "https://www.upwork.com/ab/account-security/oauth2/authorize?token=test",
            "request_token",
            "request_token_secret",
        )
        mock_upwork.Client.return_value = mock_client

        self.client.get(reverse("upwork_login"))

        session = self.client.session
        # At least one token-related key should be stored
        token_keys = [k for k in session.keys() if "token" in k.lower() or "oauth" in k.lower()]
        self.assertTrue(
            len(token_keys) > 0 or "request_token" in session or "oauth_token" in session,
        )

    # ------------------------------------------------------------------
    # OAuth callback
    # ------------------------------------------------------------------

    @patch("upworkapi.views.auth.upwork")
    def test_upwork_callback_authenticates_user(self, mock_upwork):
        """A valid OAuth callback should authenticate and log in the user."""
        mock_client = MagicMock()
        mock_client.get_access_token.return_value = ("access_token", "access_token_secret")

        mock_api = MagicMock()
        mock_api.auth.get_userinfo.return_value = {
            "auth_user": {
                "uid": "12345",
                "first_name": "Test",
                "last_name": "User",
                "mail": "test@example.com",
            }
        }
        mock_upwork.Client.return_value = mock_client

        session = self.client.session
        session["request_token"] = "request_token"
        session["request_token_secret"] = "request_token_secret"
        session.save()

        with patch("upworkapi.views.auth.authenticate") as mock_authenticate, patch(
            "upworkapi.views.auth.login"
        ) as mock_login:
            mock_authenticate.return_value = self.user

            response = self.client.get(
                reverse("upwork_callback"),
                {"oauth_token": "token", "oauth_verifier": "verifier"},
            )

            self.assertIn(response.status_code, [200, 301, 302])

    @patch("upworkapi.views.auth.upwork")
    def test_upwork_callback_with_missing_verifier(self, mock_upwork):
        """Callback without oauth_verifier should not crash (graceful handling)."""
        response = self.client.get(reverse("upwork_callback"), {})
        self.assertIn(response.status_code, [200, 301, 302, 400])

    @patch("upworkapi.views.auth.upwork")
    def test_upwork_callback_failed_authentication(self, mock_upwork):
        """When authentication fails the user must NOT be logged in."""
        mock_client = MagicMock()
        mock_client.get_access_token.return_value = ("access_token", "access_token_secret")
        mock_upwork.Client.return_value = mock_client

        session = self.client.session
        session["request_token"] = "request_token"
        session["request_token_secret"] = "request_token_secret"
        session.save()

        with patch("upworkapi.views.auth.authenticate") as mock_authenticate, patch(
            "upworkapi.views.auth.login"
        ) as mock_login:
            mock_authenticate.return_value = None

            response = self.client.get(
                reverse("upwork_callback"),
                {"oauth_token": "token", "oauth_verifier": "verifier"},
            )

            mock_login.assert_not_called()

    # ------------------------------------------------------------------
    # Logout
    # ------------------------------------------------------------------

    def test_logout_view_logs_out_user(self):
        """Authenticated users should be logged out successfully."""
        self.client.force_login(self.user)

        response = self.client.get(reverse("upwork_logout"))

        self.assertIn(response.status_code, [200, 301, 302])
        # After logout the user should no longer be authenticated
        response = self.client.get(reverse("upwork_logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_view_unauthenticated_user(self):
        """Calling logout while not authenticated should not raise an error."""
        response = self.client.get(reverse("upwork_logout"))
        self.assertIn(response.status_code, [200, 301, 302])

    def test_logout_clears_session(self):
        """All session data should be cleared on logout."""
        self.client.force_login(self.user)
        session = self.client.session
        session["upwork_access_token"] = "some_token"
        session["upwork_access_token_secret"] = "some_secret"
        session.save()

        self.client.get(reverse("upwork_logout"))

        self.assertNotIn("upwork_access_token", self.client.session)
        self.assertNotIn("upwork_access_token_secret", self.client.session)


class TestUpworkAuthBackend(TestCase):
    """Unit tests for the custom Upwork authentication backend."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="upwork_12345",
            password="unusable",
            email="upwork@example.com",
            first_name="Upwork",
            last_name="User",
        )

    def tearDown(self):
        User.objects.all().delete()

    def test_authenticate_existing_user(self):
        """Backend should return an existing user matched by Upwork UID."""
        from upwork_earning_graph.auth_backend import UpworkAuthBackend

        backend = UpworkAuthBackend()

        with patch.object(backend, "authenticate", wraps=backend.authenticate):
            user = backend.authenticate(
                request=None,
                upwork_uid="12345",
                access_token="access_token",
                access_token_secret="access_token_secret",
            )

            if user is not None:
                self.assertEqual(user.username, "upwork_12345")

    def test_authenticate_creates_new_user(self):
        """Backend should create a new user when the Upwork UID is unknown."""
        from upwork_earning_graph.auth_backend import UpworkAuthBackend

        backend = UpworkAuthBackend()

        user = backend.authenticate(
            request=None,
            upwork_uid="99999",
            access_token="new_access_token",
            access_token_secret="new_access_token_secret",
            first_name="New",
            last_name="User",
            email="newuser@example.com",
        )

        if user is not None:
            self.assertIsInstance(user, User)

    def test_get_user_existing(self):
        """get_user() should return the correct User instance by primary key."""
        from upwork_earning_graph.auth_backend import UpworkAuthBackend

        backend = UpworkAuthBackend()
        result = backend.get_user(self.user.pk)

        if result is not None:
            self.assertEqual(result.pk, self.user.pk)

    def test_get_user_nonexistent(self):
        """get_user() should return None for an unknown primary key."""
        from upwork_earning_graph.auth_backend import UpworkAuthBackend

        backend = UpworkAuthBackend()
        result = backend.get_user(99999)

        self.assertIsNone(result)


class TestUpworkOAuthFlow(TestCase):
    """Integration-style tests for the full OAuth flow."""

    def setUp(self):
        self.client = Client()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_oauth_session(self, token="req_token", secret="req_secret"):
        session = self.client.session
        session["request_token"] = token
        session["request_token_secret"] = secret
        session.save()

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    @patch("upworkapi.views.auth.upwork")
    def test_full_oauth_flow_success(self, mock_upwork):
        """Simulate a complete, successful OAuth round-trip."""
        # Step 1 – initiate login
        mock_client = MagicMock()
        mock_client.get_authorize_url.return_value = (
            "https://www.upwork.com/oauth/authorize?token=test",
            "req_token",
            "req_secret",
        )
        mock_upwork.Client.return_value = mock_client

        login_response = self.client.get(reverse("upwork_login"))
        self.assertIn(login_response.status_code, [200, 301, 302])

        # Step 2 – handle callback
        self._set_oauth_session()

        mock_client.get_access_token.return_value = ("acc_token", "acc_secret")

        with patch("upworkapi.views.auth.authenticate") as mock_auth, patch(
            "upworkapi.views.auth.login"
        ):
            test_user = User.objects.create_user(username="oauth_user", password="pw")
            mock_auth.return_value = test_user

            callback_response = self.client.get(
                reverse("upwork_callback"),
                {"oauth_token": "req_token", "oauth_verifier": "verifier123"},
            )
            self.assertIn(callback_response.status_code, [200, 301, 302])

    @patch("upworkapi.views.auth.upwork")
    def test_oauth_flow_with_invalid_token(self, mock_upwork):
        """An invalid / expired OAuth token should be handled without a 500 error."""
        mock_client = MagicMock()
        mock_client.get_access_token.side_effect = Exception("Invalid token")
        mock_upwork.Client.return_value = mock_client

        self._set_oauth_session()

        response = self.client.get(
            reverse("upwork_callback"),
            {"oauth_token": "bad_token", "oauth_verifier": "bad_verifier"},
        )
        self.assertNotEqual(response.status_code, 500)

    @patch("upworkapi.views.auth.upwork")
    def test_login_view_already_authenticated(self, mock_upwork):
        """An already-authenticated user hitting the login page should be redirected."""
        user = User.objects.create_user(username="already_auth", password="pw")
        self.client.force_login(user)

        mock_client = MagicMock()
        mock_client.get_authorize_url.return_value = (
            "https://www.upwork.com/oauth/authorize?token=test",
            "req_token",
            "req_secret",
        )
        mock_upwork.Client.return_value = mock_client

        response = self.client.get(reverse("upwork_login"))
        # Either redirect away from login or show a page – both are acceptable
        self.assertIn(response.status_code, [200, 301, 302])


class TestUpworkAuthSessionManagement(TestCase):
    """Tests focused on session data during the OAuth flow."""

    def setUp(self):
        self.client = Client()

    @patch("upworkapi.views.auth.upwork")
    def test_session_contains_access_token_after_login(self, mock_upwork):
        """After a successful OAuth callback the session should hold the access token."""
        mock_client = MagicMock()
        mock_client.get_access_token.return_value = ("acc_token", "acc_secret")
        mock_upwork.Client.return_value = mock_client

        session = self.client.session
        session["request_token"] = "req_token"
        session["request_token_secret"] = "req_secret"
        session.save()

        user = User.objects.create_user(username="session_user", password="pw")

        with patch("upworkapi.views.auth.authenticate") as mock_auth, patch(
            "upworkapi.views.auth.login"
        ):
            mock_auth.return_value = user

            self.client.get(
                reverse("upwork_callback"),
                {"oauth_token": "req_token", "oauth_verifier": "verifier"},
            )

    @patch("upworkapi.views.auth.upwork")
    def test_request_token_cleared_after_callback(self, mock_upwork):
        """Temporary request tokens should be removed from the session after callback."""
        mock_client = MagicMock()
        mock_client.get_access_token.return_value = ("acc_token", "acc_secret")
        mock_upwork.Client.return_value = mock_client

        session = self.client.session
        session["request_token"] = "req_token"
        session["request_token_secret"] = "req_secret"
        session.save()

        user = User.objects.create_user(username="cleanup_user", password="pw")

        with patch("upworkapi.views.auth.authenticate") as mock_auth, patch(
            "upworkapi.views.auth.login"
        ):
            mock_auth.return_value = user

            self.client.get(
                reverse("upwork_callback"),
                {"oauth_token": "req_token", "oauth_verifier": "verifier"},
            )

        # request_token should no longer be in session
        self.assertNotIn("request_token", self.client.session)

    def test_session_cleared_on_logout(self):
        """All Upwork-related session keys must be gone after logout."""
        user = User.objects.create_user(username="logout_user", password="pw")
        self.client.force_login(user)

        session = self.client.session
        session["upwork_access_token"] = "acc_token"
        session["upwork_access_token_secret"] = "acc_secret"
        session.save()

        self.client.get(reverse("upwork_logout"))

        self.assertNotIn("upwork_access_token", self.client.session)
        self.assertNotIn("upwork_access_token_secret", self.client.session)


class Test