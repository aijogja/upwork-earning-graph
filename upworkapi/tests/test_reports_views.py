from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.cache import cache
from unittest.mock import patch, MagicMock
from datetime import datetime
from upworkapi.views.reports import (
    DEFAULT_ALL_TIME_START_YEAR,
    _month_week_ranges,
    earning_graph_annually,
    earning_graph_monthly,
    timereport_weekly,
    _cached_earliest_earning_year,
    _cached_earliest_time_report_year,
    _cached_upwork_join_year,
    _extract_client_name,
    _find_first_key,
    _get,
    _parse_year,
)


class MonthWeekRangesTestCase(TestCase):

    def test_month_week_ranges_january_2024(self):
        ranges = _month_week_ranges(2024, 1)
        self.assertIsInstance(ranges, list)
        self.assertTrue(len(ranges) > 0)
        for label, start, end in ranges:
            self.assertTrue(label.startswith("W"))
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
        data = {"key": "value", "number": 42}
        self.assertEqual(_get(data, "key"), "value")
        self.assertEqual(_get(data, "number"), 42)
        self.assertEqual(_get(data, "missing", "default"), "default")

    def test_get_with_object(self):
        class TestObj:
            key = "value"
            number = 42

        obj = TestObj()
        self.assertEqual(_get(obj, "key"), "value")
        self.assertEqual(_get(obj, "number"), 42)
        self.assertEqual(_get(obj, "missing", "default"), "default")

    def test_extract_client_name_from_dict(self):
        detail = {"description": "Test Client - some work"}
        result = _extract_client_name(detail)
        self.assertEqual(result, "Test Client")

    def test_extract_client_name_from_description(self):
        detail = {"description": "Client ABC - Project work"}
        self.assertEqual(_extract_client_name(detail), "Client ABC")

    def test_extract_client_name_unknown(self):
        detail = {}
        self.assertEqual(_extract_client_name(detail), "Unknown")

    def test_parse_year_from_date_string(self):
        self.assertEqual(_parse_year("2014-03-12T10:20:30Z"), 2014)

    def test_parse_year_from_numeric_string_timestamp(self):
        self.assertEqual(_parse_year("1453334400000"), 2016)

    def test_find_first_key_nested_dict(self):
        data = {
            "data": {
                "talentVPDAuthProfile": {
                    "stats": {"memberSince": "2013-09-19T07:15:53.000Z"}
                }
            }
        }
        self.assertEqual(
            _find_first_key(data, "memberSince"), "2013-09-19T07:15:53.000Z"
        )

    @patch("upworkapi.views.reports.graphql.Api")
    @patch("upworkapi.views.reports.upwork_client.get_client")
    def test_cached_upwork_join_year_uses_member_since(
        self, mock_get_client, mock_graphql_api
    ):
        cache.clear()
        request = MagicMock()
        request.user.id = 101
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_api = MagicMock()
        mock_api.execute.return_value = {
            "data": {
                "talentVPDAuthProfile": {
                    "stats": {
                        "memberSince": "2013-09-19T07:15:53.000Z",
                    }
                }
            }
        }
        mock_graphql_api.return_value = mock_api

        year = _cached_upwork_join_year(
            request,
            token={"access_token": "test_token"},
            tenant_id="tenant",
            freelancer_reference="freelancer",
        )

        self.assertEqual(year, 2013)
        executed_query = mock_api.execute.call_args.args[0]["query"]
        self.assertIn("memberSince", executed_query)

    @patch("upworkapi.views.reports.graphql.Api")
    @patch("upworkapi.views.reports.upwork_client.get_client")
    def test_cached_upwork_join_year_falls_back_to_created_year(
        self, mock_get_client, mock_graphql_api
    ):
        cache.clear()
        request = MagicMock()
        request.user.id = 103
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_api = MagicMock()
        mock_api.execute.side_effect = [
            Exception("Cannot query field talentVPDAuthProfile"),
            Exception("Cannot query field joinDateTime"),
            Exception("Cannot query field joinDateTime"),
            Exception("Field joinDateTime must not have a selection"),
            Exception("Field joinDateTime must not have a selection"),
            {
                "data": {
                    "user": {
                        "createdDateTime": "2015-02-11T00:00:00Z",
                    }
                }
            },
        ]
        mock_graphql_api.return_value = mock_api

        year = _cached_upwork_join_year(
            request,
            token={"access_token": "test_token"},
            tenant_id="tenant",
            freelancer_reference="freelancer",
        )

        self.assertEqual(year, 2015)
        self.assertEqual(mock_api.execute.call_count, 6)

    @patch("upworkapi.views.reports.graphql.Api")
    @patch("upworkapi.views.reports.upwork_client.get_client")
    def test_cached_upwork_join_year_falls_back_to_2005(
        self, mock_get_client, mock_graphql_api
    ):
        cache.clear()
        request = MagicMock()
        request.user.id = 102
        mock_get_client.side_effect = Exception("Upwork unavailable")

        year = _cached_upwork_join_year(
            request,
            token={"access_token": "test_token"},
            tenant_id="tenant",
            freelancer_reference="freelancer",
        )

        self.assertEqual(year, DEFAULT_ALL_TIME_START_YEAR)

    @patch("upworkapi.views.reports.fetch_transaction_history_rows")
    @patch("upworkapi.views.reports._time_report_rows_for_year_range")
    def test_cached_earliest_earning_year_uses_earliest_actual_earning(
        self, mock_time_report_rows, mock_transaction_rows
    ):
        cache.clear()
        request = MagicMock()
        request.user.id = 104
        mock_time_report_rows.return_value = [
            {
                "dateWorkedOn": "2017-04-10",
                "totalCharges": "120.00",
                "totalHoursWorked": 4,
            }
        ]
        mock_transaction_rows.return_value = [
            {
                "date": "2016-08-01T00:00:00Z",
                "occurred_at": "2016-08-01T00:00:00Z",
                "amount": 250.0,
                "kind": "Fixed",
                "subtype": "Fixed price",
                "description": "Fixed price milestone",
            }
        ]

        year = _cached_earliest_earning_year(
            request,
            token={"access_token": "test_token"},
            tenant_id="tenant",
            tenant_ids=["tenant"],
            freelancer_reference="freelancer",
            fallback_year=2013,
        )

        self.assertEqual(year, 2016)

    @patch("upworkapi.views.reports._time_report_rows_for_year_range")
    def test_cached_earliest_time_report_year_uses_hours_when_charges_are_zero(
        self, mock_time_report_rows
    ):
        cache.clear()
        request = MagicMock()
        request.user.id = 105
        mock_time_report_rows.return_value = [
            {
                "dateWorkedOn": "2018-01-02",
                "totalCharges": "0",
                "totalHoursWorked": 2.5,
            }
        ]

        year = _cached_earliest_time_report_year(
            request,
            token={"access_token": "test_token"},
            tenant_id="tenant",
            freelancer_reference="freelancer",
            fallback_year=2013,
        )

        self.assertEqual(year, 2018)


class EarningGraphAnnuallyTestCase(TestCase):

    @patch("upworkapi.views.reports.graphql.Api")
    @patch("upworkapi.views.reports.upwork_client.get_client")
    def test_earning_graph_annually_success(self, mock_get_client, mock_graphql_api):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_api = MagicMock()
        mock_api.execute.return_value = {
            "data": {
                "user": {
                    "freelancerProfile": {
                        "user": {
                            "timeReport": [
                                {
                                    "dateWorkedOn": "2024-01-15",
                                    "totalCharges": "100.50",
                                    "memo": "Test work",
                                    "contract": {
                                        "offer": {"client": {"name": "Test Client"}}
                                    },
                                },
                                {
                                    "dateWorkedOn": "2024-02-20",
                                    "totalCharges": "200.75",
                                    "memo": "More work",
                                    "contract": {
                                        "offer": {"client": {"name": "Another Client"}}
                                    },
                                },
                            ]
                        }
                    }
                }
            }
        }
        mock_graphql_api.return_value = mock_api

        token = {"access_token": "test_token"}
        result = earning_graph_annually(token, "2024")

        self.assertEqual(result["year"], "2024")
        self.assertIn("report", result)
        self.assertIn("detail_earning", result)
        self.assertIn("total_earning", result)
        self.assertIn("charity", result)
        self.assertEqual(len(result["report"]), 12)
        self.assertEqual(len(result["detail_earning"]), 2)

    @patch("upworkapi.views.reports.graphql.Api")
    @patch("upworkapi.views.reports.upwork_client.get_client")
    def test_earning_graph_annually_empty_data(self, mock_get_client, mock_graphql_api):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_api = MagicMock()
        mock_api.execute.return_value = {
            "data": {"user": {"freelancerProfile": {"user": {"timeReport": []}}}}
        }
        mock_graphql_api.return_value = mock_api

        token = {"access_token": "test_token"}
        result = earning_graph_annually(token, "2024")

        self.assertEqual(result["total_earning"], 0.0)
        self.assertEqual(len(result["detail_earning"]), 0)


class EarningGraphMonthlyTestCase(TestCase):

    @patch("upworkapi.views.reports.graphql.Api")
    @patch("upworkapi.views.reports.upwork_client.get_client")
    def test_earning_graph_monthly_success(self, mock_get_client, mock_graphql_api):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_api = MagicMock()
        mock_api.execute.return_value = {
            "data": {
                "user": {
                    "freelancerProfile": {
                        "user": {
                            "timeReport": [
                                {
                                    "dateWorkedOn": "2024-01-15",
                                    "totalCharges": "100.50",
                                    "memo": "Test work",
                                    "contract": {
                                        "offer": {"client": {"name": "Test Client"}}
                                    },
                                }
                            ]
                        }
                    }
                }
            }
        }
        mock_graphql_api.return_value = mock_api

        token = {"access_token": "test_token"}
        result = earning_graph_monthly(token, 2024, 1)

        self.assertEqual(result["year"], "2024")
        self.assertEqual(result["month"], "January")
        self.assertIn("report", result)
        self.assertIn("detail_earning", result)
        self.assertIn("total_earning", result)


class TimereportWeeklyTestCase(TestCase):

    @patch("upworkapi.views.reports.graphql.Api")
    @patch("upworkapi.views.reports.upwork_client.get_client")
    def test_timereport_weekly_success(self, mock_get_client, mock_graphql_api):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_api = MagicMock()
        mock_api.execute.return_value = {
            "data": {
                "user": {
                    "freelancerProfile": {
                        "user": {
                            "timeReport": [
                                {"dateWorkedOn": "2024-01-15", "totalHoursWorked": 8.5},
                                {"dateWorkedOn": "2024-01-16", "totalHoursWorked": 7.0},
                            ]
                        }
                    }
                }
            }
        }
        mock_graphql_api.return_value = mock_api

        token = {"access_token": "test_token"}
        result = timereport_weekly(token, "2024")

        self.assertEqual(result["year"], "2024")
        self.assertIn("report", result)
        self.assertIn("total_hours", result)
        self.assertIn("avg_week", result)
        self.assertIn("work_status", result)


class EarningGraphViewTestCase(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", password="testpass")

    def test_earning_graph_requires_login(self):
        response = self.client.get(reverse("earning_graph"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/"))

    @patch("upworkapi.views.reports.earning_graph_annually")
    def test_earning_graph_logged_in_annual(self, mock_earning_annually):
        self.client.force_login(self.user)
        session = self.client.session
        session["token"] = {"access_token": "test_token"}
        session.save()

        mock_earning_annually.return_value = {
            "year": "2024",
            "report": [],
            "detail_earning": [],
            "total_earning": 0.0,
            "charity": 0.0,
            "x_axis": [],
            "title": "Test",
            "tooltip": "test",
        }

        response = self.client.get(reverse("earning_graph"), {"year": "2024"})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "upworkapi/finance.html")

    @patch("upworkapi.views.reports.earning_graph_monthly")
    def test_earning_graph_logged_in_monthly(self, mock_earning_monthly):
        self.client.force_login(self.user)
        session = self.client.session
        session["token"] = {"access_token": "test_token"}
        session.save()

        mock_earning_monthly.return_value = {
            "year": "2024",
            "month": "January",
            "report": [],
            "detail_earning": [],
            "total_earning": 0.0,
            "charity": 0.0,
            "x_axis": [],
            "title": "Test",
            "tooltip": "test",
        }

        response = self.client.post(
            reverse("earning_graph"), {"year": "2024", "month": "1"}
        )
        self.assertEqual(response.status_code, 200)

    def test_earning_graph_invalid_year_format(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["token"] = {"access_token": "test_token"}
        session.save()

        response = self.client.get(reverse("earning_graph"), {"year": "invalid"})
        self.assertEqual(response.status_code, 302)


class TimereportGraphViewTestCase(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", password="testpass")

    def test_timereport_graph_requires_login(self):
        response = self.client.get(reverse("timereport_graph"))
        self.assertEqual(response.status_code, 302)

    @patch("upworkapi.views.reports.timereport_weekly")
    def test_timereport_graph_logged_in(self, mock_timereport):
        self.client.force_login(self.user)
        session = self.client.session
        session["token"] = {"access_token": "test_token"}
        session.save()

        mock_timereport.return_value = {
            "year": "2024",
            "report": [],
            "total_hours": 0,
            "avg_week": 0.0,
            "work_status": "success",
            "x_axis": [],
            "title": "Test",
            "tooltip": "test",
        }

        response = self.client.get(reverse("timereport_graph"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "upworkapi/timereport.html")


class AllTimeHourlyGraphViewTestCase(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="hourlyuser", password="testpass")

    @patch("upworkapi.views.reports._warm_all_time_hourly_years_async")
    @patch("upworkapi.views.reports._cached_earliest_time_report_year")
    @patch("upworkapi.views.reports._cached_upwork_join_year")
    def test_all_time_hourly_searches_from_earliest_supported_year(
        self, mock_join_year, mock_earliest_year, mock_warm
    ):
        cache.clear()
        self.client.force_login(self.user)
        session = self.client.session
        session["token"] = {"access_token": "test_token"}
        session.save()

        mock_join_year.return_value = 2020
        mock_earliest_year.return_value = 2017
        mock_warm.return_value = True

        response = self.client.get(reverse("all_time_hourly_graph"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_earliest_year.call_args.kwargs["fallback_year"],
            DEFAULT_ALL_TIME_START_YEAR,
        )


class ReportsURLTestCase(TestCase):

    def test_earning_graph_url_resolves(self):
        url = reverse("earning_graph")
        self.assertEqual(url, "/earning/")

    def test_timereport_graph_url_resolves(self):
        url = reverse("timereport_graph")
        self.assertEqual(url, "/timereport/")
