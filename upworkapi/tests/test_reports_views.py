from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from unittest.mock import patch, MagicMock
from datetime import datetime
from upworkapi.views.reports import (
    _month_week_ranges,
    earning_graph_annually,
    earning_graph_monthly,
    timereport_weekly,
    _extract_client_name,
    _get
)


class MonthWeekRangesTestCase(TestCase):

    def test_month_week_ranges_january_2024(self):
        ranges = _month_week_ranges(2024, 1)
        self.assertIsInstance(ranges, list)
        self.assertTrue(len(ranges) > 0)
        for label, start, end in ranges:
            self.assertTrue(label.startswith('W'))
            self.assertLessEqual(start, end)

    def test_month_week_ranges_december_2024(self):
        ranges = _month_week_ranges(2024, 12)
        self.assertIsInstance(ranges, list)
        self.assertTrue(len(ranges) > 0)

    def test_month_week_ranges_february_leap_year(self):
        ranges = _month_week_ranges(2024, 2)
        self.assertIsInstance(ranges, list)
        self.assertTrue(len(ranges) > 0)


class HelperFunctionsTestCase(TestCase):

    def test_get_with_dict(self):
        data = {'key': 'value', 'number': 42}
        self.assertEqual(_get(data, 'key'), 'value')
        self.assertEqual(_get(data, 'number'), 42)
        self.assertEqual(_get(data, 'missing', 'default'), 'default')

    def test_get_with_object(self):
        class TestObj:
            key = 'value'
            number = 42

        obj = TestObj()
        self.assertEqual(_get(obj, 'key'), 'value')
        self.assertEqual(_get(obj, 'number'), 42)
        self.assertEqual(_get(obj, 'missing', 'default'), 'default')

    def test_extract_client_name_from_dict(self):
        detail = {'description': 'Test Client - some work'}
        result = _extract_client_name(detail)
        self.assertEqual(result, 'Test Client')

    def test_extract_client_name_from_description(self):
        detail = {'description': 'Client ABC - Project work'}
        self.assertEqual(_extract_client_name(detail), 'Client ABC')

    def test_extract_client_name_unknown(self):
        detail = {}
        self.assertEqual(_extract_client_name(detail), 'Unknown')


class EarningGraphAnnuallyTestCase(TestCase):

    @patch('upworkapi.views.reports.graphql.Api')
    @patch('upworkapi.views.reports.upwork_client.get_client')
    def test_earning_graph_annually_success(self, mock_get_client, mock_graphql_api):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_api = MagicMock()
        mock_api.execute.return_value = {
            'data': {
                'user': {
                    'freelancerProfile': {
                        'user': {
                            'timeReport': [
                                {
                                    'dateWorkedOn': '2024-01-15',
                                    'totalCharges': '100.50',
                                    'memo': 'Test work',
                                    'contract': {
                                        'offer': {
                                            'client': {
                                                'name': 'Test Client'
                                            }
                                        }
                                    }
                                },
                                {
                                    'dateWorkedOn': '2024-02-20',
                                    'totalCharges': '200.75',
                                    'memo': 'More work',
                                    'contract': {
                                        'offer': {
                                            'client': {
                                                'name': 'Another Client'
                                            }
                                        }
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        }
        mock_graphql_api.return_value = mock_api

        token = {'access_token': 'test_token'}
        result = earning_graph_annually(token, '2024')

        self.assertEqual(result['year'], '2024')
        self.assertIn('report', result)
        self.assertIn('detail_earning', result)
        self.assertIn('total_earning', result)
        self.assertIn('charity', result)
        self.assertEqual(len(result['report']), 12)
        self.assertEqual(len(result['detail_earning']), 2)

    @patch('upworkapi.views.reports.graphql.Api')
    @patch('upworkapi.views.reports.upwork_client.get_client')
    def test_earning_graph_annually_empty_data(self, mock_get_client, mock_graphql_api):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_api = MagicMock()
        mock_api.execute.return_value = {
            'data': {
                'user': {
                    'freelancerProfile': {
                        'user': {
                            'timeReport': []
                        }
                    }
                }
            }
        }
        mock_graphql_api.return_value = mock_api

        token = {'access_token': 'test_token'}
        result = earning_graph_annually(token, '2024')

        self.assertEqual(result['total_earning'], 0.0)
        self.assertEqual(len(result['detail_earning']), 0)


class EarningGraphMonthlyTestCase(TestCase):

    @patch('upworkapi.views.reports.graphql.Api')
    @patch('upworkapi.views.reports.upwork_client.get_client')
    def test_earning_graph_monthly_success(self, mock_get_client, mock_graphql_api):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_api = MagicMock()
        mock_api.execute.return_value = {
            'data': {
                'user': {
                    'freelancerProfile': {
                        'user': {
                            'timeReport': [
                                {
                                    'dateWorkedOn': '2024-01-15',
                                    'totalCharges': '100.50',
                                    'memo': 'Test work',
                                    'contract': {
                                        'offer': {
                                            'client': {
                                                'name': 'Test Client'
                                            }
                                        }
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        }
        mock_graphql_api.return_value = mock_api

        token = {'access_token': 'test_token'}
        result = earning_graph_monthly(token, 2024, 1)

        self.assertEqual(result['year'], '2024')
        self.assertEqual(result['month'], 'January')
        self.assertIn('report', result)
        self.assertIn('detail_earning', result)
        self.assertIn('total_earning', result)


class TimereportWeeklyTestCase(TestCase):

    @patch('upworkapi.views.reports.graphql.Api')
    @patch('upworkapi.views.reports.upwork_client.get_client')
    def test_timereport_weekly_success(self, mock_get_client, mock_graphql_api):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_api = MagicMock()
        mock_api.execute.return_value = {
            'data': {
                'user': {
                    'freelancerProfile': {
                        'user': {
                            'timeReport': [
                                {
                                    'dateWorkedOn': '2024-01-15',
                                    'totalHoursWorked': 8.5
                                },
                                {
                                    'dateWorkedOn': '2024-01-16',
                                    'totalHoursWorked': 7.0
                                }
                            ]
                        }
                    }
                }
            }
        }
        mock_graphql_api.return_value = mock_api

        token = {'access_token': 'test_token'}
        result = timereport_weekly(token, '2024')

        self.assertEqual(result['year'], '2024')
        self.assertIn('report', result)
        self.assertIn('total_hours', result)
        self.assertIn('avg_week', result)
        self.assertIn('work_status', result)


class EarningGraphViewTestCase(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='testpass')

    def test_earning_graph_requires_login(self):
        response = self.client.get(reverse('earning_graph'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/'))

    @patch('upworkapi.views.reports.earning_graph_annually')
    def test_earning_graph_logged_in_annual(self, mock_earning_annually):
        self.client.force_login(self.user)
        session = self.client.session
        session['token'] = {'access_token': 'test_token'}
        session.save()

        mock_earning_annually.return_value = {
            'year': '2024',
            'report': [],
            'detail_earning': [],
            'total_earning': 0.0,
            'charity': 0.0,
            'x_axis': [],
            'title': 'Test',
            'tooltip': 'test'
        }

        response = self.client.get(reverse('earning_graph'), {'year': '2024'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'upworkapi/finance.html')

    @patch('upworkapi.views.reports.earning_graph_monthly')
    def test_earning_graph_logged_in_monthly(self, mock_earning_monthly):
        self.client.force_login(self.user)
        session = self.client.session
        session['token'] = {'access_token': 'test_token'}
        session.save()

        mock_earning_monthly.return_value = {
            'year': '2024',
            'month': 'January',
            'report': [],
            'detail_earning': [],
            'total_earning': 0.0,
            'charity': 0.0,
            'x_axis': [],
            'title': 'Test',
            'tooltip': 'test'
        }

        response = self.client.post(reverse('earning_graph'), {'year': '2024', 'month': '1'})
        self.assertEqual(response.status_code, 200)

    def test_earning_graph_invalid_year_format(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['token'] = {'access_token': 'test_token'}
        session.save()

        response = self.client.get(reverse('earning_graph'), {'year': 'invalid'})
        self.assertEqual(response.status_code, 302)


class TimereportGraphViewTestCase(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='testpass')

    def test_timereport_graph_requires_login(self):
        response = self.client.get(reverse('timereport_graph'))
        self.assertEqual(response.status_code, 302)

    @patch('upworkapi.views.reports.timereport_weekly')
    def test_timereport_graph_logged_in(self, mock_timereport):
        self.client.force_login(self.user)
        session = self.client.session
        session['token'] = {'access_token': 'test_token'}
        session.save()

        mock_timereport.return_value = {
            'year': '2024',
            'report': [],
            'total_hours': 0,
            'avg_week': 0.0,
            'work_status': 'success',
            'x_axis': [],
            'title': 'Test',
            'tooltip': 'test'
        }

        response = self.client.get(reverse('timereport_graph'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'upworkapi/timereport.html')


class ReportsURLTestCase(TestCase):

    def test_earning_graph_url_resolves(self):
        url = reverse('earning_graph')
        self.assertEqual(url, '/earning/')

    def test_timereport_graph_url_resolves(self):
        url = reverse('timereport_graph')
        self.assertEqual(url, '/timereport/')
