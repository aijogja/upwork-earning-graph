from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
import json


class DebugViewTestCase(TestCase):

    def setUp(self):
        self.client = Client()

    def test_session_dump_without_session(self):
        response = self.client.get('/debug/session/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')

        data = json.loads(response.content)
        self.assertIn('has_token', data)
        self.assertIn('token_keys', data)
        self.assertIn('has_upwork_auth', data)
        self.assertIn('upwork_auth', data)
        self.assertIn('is_authenticated', data)
        self.assertIn('user', data)

        self.assertFalse(data['has_token'])
        self.assertFalse(data['has_upwork_auth'])
        self.assertFalse(data['is_authenticated'])

    def test_session_dump_with_token(self):
        session = self.client.session
        session['token'] = {
            'access_token': 'test_token',
            'refresh_token': 'test_refresh',
            'expires_in': 3600
        }
        session.save()

        response = self.client.get('/debug/session/')
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertTrue(data['has_token'])
        self.assertEqual(len(data['token_keys']), 3)
        self.assertIn('access_token', data['token_keys'])

    def test_session_dump_with_upwork_auth(self):
        session = self.client.session
        session['upwork_auth'] = {
            'fullname': 'Test User',
            'profile_picture': 'https://example.com/pic.jpg',
            'profile_url': 'https://upwork.com/profile'
        }
        session.save()

        response = self.client.get('/debug/session/')
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertTrue(data['has_upwork_auth'])
        self.assertIsNotNone(data['upwork_auth'])
        self.assertEqual(data['upwork_auth']['fullname'], 'Test User')

    def test_session_dump_with_authenticated_user(self):
        user = User.objects.create_user(username='testuser', password='testpass')
        self.client.force_login(user)

        response = self.client.get('/debug/session/')
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertTrue(data['is_authenticated'])
        self.assertEqual(data['user'], 'testuser')

    def test_session_dump_full_session(self):
        user = User.objects.create_user(username='testuser', password='testpass')
        self.client.force_login(user)

        session = self.client.session
        session['token'] = {'access_token': 'test_token'}
        session['upwork_auth'] = {'fullname': 'Test User'}
        session.save()

        response = self.client.get('/debug/session/')
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertTrue(data['has_token'])
        self.assertTrue(data['has_upwork_auth'])
        self.assertTrue(data['is_authenticated'])
        self.assertEqual(data['user'], 'testuser')

    def test_session_dump_returns_json_response(self):
        response = self.client.get('/debug/session/')
        self.assertIsInstance(json.loads(response.content), dict)
