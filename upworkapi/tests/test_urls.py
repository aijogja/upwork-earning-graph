from django.test import TestCase
from django.urls import reverse, resolve
from upworkapi.views import auth, reports, debug


class URLPatternsTestCase(TestCase):

    def test_auth_url_pattern(self):
        url = reverse('auth')
        self.assertEqual(url, '/auth/')
        self.assertEqual(resolve(url).func, auth.auth_view)

    def test_callback_url_pattern(self):
        url = reverse('callback')
        self.assertEqual(url, '/callback/')
        self.assertEqual(resolve(url).func, auth.callback)

    def test_logout_url_pattern(self):
        url = reverse('logout')
        self.assertEqual(url, '/logout/')
        self.assertEqual(resolve(url).func, auth.disconnect)

    def test_earning_graph_url_pattern(self):
        url = reverse('earning_graph')
        self.assertEqual(url, '/earning/')
        self.assertEqual(resolve(url).func, reports.earning_graph)

    def test_earning_graph_with_slash_url_pattern(self):
        url = '/earning/'
        self.assertEqual(resolve(url).func, reports.earning_graph)

    def test_timereport_graph_url_pattern(self):
        url = reverse('timereport_graph')
        self.assertEqual(url, '/timereport/')
        self.assertEqual(resolve(url).func, reports.timereport_graph)

    def test_timereport_graph_with_slash_url_pattern(self):
        url = '/timereport/'
        self.assertEqual(resolve(url).func, reports.timereport_graph)

    def test_earning_month_client_detail_url_pattern(self):
        url = reverse('earning_month_client_detail', kwargs={
            'year': 2024,
            'month': 1,
            'client_name': 'TestClient'
        })
        self.assertEqual(url, '/earning/2024/1/client/TestClient/')
        self.assertEqual(resolve(url).func, reports.earning_month_client_detail)

    def test_debug_session_url_pattern(self):
        url = '/debug/session/'
        self.assertEqual(resolve(url).func, debug.session_dump)

    def test_admin_url_pattern(self):
        url = '/admin/'
        self.assertEqual(resolve(url).app_name, 'admin')


class URLReverseTestCase(TestCase):

    def test_reverse_home(self):
        url = reverse('home')
        self.assertEqual(url, '/')

    def test_reverse_about(self):
        url = reverse('about')
        self.assertEqual(url, '/about/')

    def test_reverse_contact(self):
        url = reverse('contact')
        self.assertEqual(url, '/contact/')

    def test_reverse_auth(self):
        url = reverse('auth')
        self.assertEqual(url, '/auth/')

    def test_reverse_callback(self):
        url = reverse('callback')
        self.assertEqual(url, '/callback/')

    def test_reverse_logout(self):
        url = reverse('logout')
        self.assertEqual(url, '/logout/')

    def test_reverse_earning_graph(self):
        url = reverse('earning_graph')
        self.assertEqual(url, '/earning/')

    def test_reverse_timereport_graph(self):
        url = reverse('timereport_graph')
        self.assertEqual(url, '/timereport/')

    def test_reverse_earning_month_client_detail(self):
        url = reverse('earning_month_client_detail', kwargs={
            'year': 2024,
            'month': 3,
            'client_name': 'ABC Corp'
        })
        self.assertEqual(url, '/earning/2024/3/client/ABC%20Corp/')


class URLParametersTestCase(TestCase):

    def test_earning_month_client_detail_with_different_years(self):
        for year in [2020, 2021, 2022, 2023, 2024]:
            url = reverse('earning_month_client_detail', kwargs={
                'year': year,
                'month': 1,
                'client_name': 'TestClient'
            })
            self.assertIn(str(year), url)

    def test_earning_month_client_detail_with_different_months(self):
        for month in range(1, 13):
            url = reverse('earning_month_client_detail', kwargs={
                'year': 2024,
                'month': month,
                'client_name': 'TestClient'
            })
            self.assertIn(str(month), url)

    def test_earning_month_client_detail_with_special_characters_in_client_name(self):
        url = reverse('earning_month_client_detail', kwargs={
            'year': 2024,
            'month': 1,
            'client_name': 'Client & Co.'
        })
        self.assertIn('Client', url)
