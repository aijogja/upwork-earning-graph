from calendar import month_name, monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
import calendar
import json
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import redirect, render
from oauthlib.oauth2 import InvalidGrantError
from upwork.routers import graphql

from upworkapi.services.transactions import fetch_fixed_price_transactions
from upworkapi.utils import upwork_client


CACHE_TTL_SECONDS = 900


def _cache_key(prefix: str, *parts) -> str:
    safe_parts = [str(p) for p in parts if p is not None]
    return prefix + ":" + ":".join(safe_parts)


def _date_key(d) -> str:
    if isinstance(d, datetime):
        return d.strftime("%Y%m%d")
    if isinstance(d, date):
        return d.strftime("%Y%m%d")
    return str(d)


def _cached_earning_graph_annually(request, token, year):
    key = _cache_key("hourly_year", request.user.id, year)
    cached = cache.get(key)
    if cached is not None:
        return cached
    data = earning_graph_annually(token, year)
    cache.set(key, data, CACHE_TTL_SECONDS)
    return data


def _cached_earning_graph_monthly(request, token, year, month):
    key = _cache_key("hourly_month", request.user.id, year, month)
    cached = cache.get(key)
    if cached is not None:
        return cached
    data = earning_graph_monthly(token, year, month)
    cache.set(key, data, CACHE_TTL_SECONDS)
    return data


def _cached_fixed_price_transactions(
    request,
    *,
    token,
    freelancer_reference,
    tenant_id,
    start_date,
    end_date,
    debug=False,
):
    if debug:
        return fetch_fixed_price_transactions(
            token=token,
            freelancer_reference=freelancer_reference,
            tenant_id=tenant_id,
            start_date=start_date,
            end_date=end_date,
            debug=debug,
        )

    key = _cache_key(
        "fixed_tx",
        request.user.id,
        tenant_id or "",
        freelancer_reference,
        _date_key(start_date),
        _date_key(end_date),
    )
    cached = cache.get(key)
    if cached is not None:
        return cached

    rows = fetch_fixed_price_transactions(
        token=token,
        freelancer_reference=freelancer_reference,
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        debug=debug,
    )
    cache.set(key, rows, CACHE_TTL_SECONDS)
    return rows


def _month_week_ranges(year: int, month: int):
    first = datetime(year, month, 1).date()
    if month == 12:
        next_month = datetime(year + 1, 1, 1).date()
    else:
        next_month = datetime(year, month + 1, 1).date()
    last = next_month - timedelta(days=1)

    start = first - timedelta(days=first.weekday())
    end = last + timedelta(days=(6 - last.weekday()))

    ranges = []
    w = 1
    cur = start
    while cur <= end:
        ws = cur
        we = cur + timedelta(days=6)
        clip_s = max(ws, first)
        clip_e = min(we, last)
        if clip_s <= clip_e:
            ranges.append((f"W{w}", clip_s, clip_e))
            w += 1
        cur += timedelta(days=7)
    return ranges


def earning_graph_annually(token, year):
    client = upwork_client.get_client(token)

    list_month = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]

    start_date = f"{year}0101"
    end_date = f"{year}1231"

    query = """query User {
        user {
            freelancerProfile {
                user {
                    timeReport(timeReportDate_bt: { rangeStart: "%s", rangeEnd: "%s" }) {
                        dateWorkedOn
                        totalCharges
                        memo
                        contract {
                            offer {
                                client { name }
                            }
                        }
                    }
                }
            }
        }
    }""" % (
        start_date,
        end_date,
    )

    response = graphql.Api(client).execute({"query": query})
    rows = response["data"]["user"]["freelancerProfile"]["user"]["timeReport"]

    month_totals = {i: 0.0 for i in range(1, 13)}
    total_earning = 0.0
    detail = []

    for r in rows:
        dt = datetime.strptime(r["dateWorkedOn"], "%Y-%m-%d").date()
        amt = float((r.get("totalCharges") or 0) or 0)

        month_totals[dt.month] += amt
        total_earning += amt

        client_name = (
            ((r.get("contract") or {}).get("offer") or {}).get("client") or {}
        ).get("name") or "Unknown"

        memo = r.get("memo") or ""
        detail.append(
            {
                "date": r["dateWorkedOn"],
                "month": str(dt.month),
                "amount": r.get("totalCharges") or 0,
                "description": f"{client_name} - {memo}",
                "client_name": client_name,
            }
        )

    report = [{"y": round(month_totals[i], 2), "month": str(i)} for i in range(1, 13)]

    total_earning = round(total_earning, 2)
    tooltip = "'<b>'+this.x+'</b><br/>'+this.series.name+': $ '+this.y"

    return {
        "year": year,
        "x_axis": list_month,
        "report": report,
        "detail_earning": detail,
        "total_earning": total_earning,
        "charity": round(total_earning * 0.025, 2),
        "title": "Year : %s ($ %s)" % (year, total_earning),
        "tooltip": tooltip,
    }


def earning_graph_monthly(token, year, month):
    client = upwork_client.get_client(token)

    year_str = str(year)
    month_str = f"{month:02d}"
    count_day = monthrange(year, month)[1]
    start_date = f"{year_str}{month_str}01"
    end_date = f"{year_str}{month_str}{count_day:02d}"

    query = """query User {
            user {
                freelancerProfile {
                    user {
                        timeReport(timeReportDate_bt: { rangeStart: "%s", rangeEnd: "%s" }) {
                            dateWorkedOn
                            totalCharges
                            memo
                            contract {
                                offer {
                                    client {
                                        name
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    """ % (
        start_date,
        end_date,
    )

    response = graphql.Api(client).execute({"query": query})

    earning_report = response["data"]["user"]["freelancerProfile"]["user"]["timeReport"]

    week_ranges = _month_week_ranges(year, month)
    x_axis = [wlabel for (wlabel, _, _) in week_ranges]

    week_totals = {wlabel: 0.0 for wlabel in x_axis}
    list_report = []
    total_earning = 0.0

    for m in earning_report:
        d = datetime.strptime(m["dateWorkedOn"], "%Y-%m-%d").date()
        amt = float(m["totalCharges"])

        for wlabel, ws, we in week_ranges:
            if ws <= d <= we:
                week_totals[wlabel] += amt
                list_report.append(
                    {
                        "date": m["dateWorkedOn"],
                        "week": wlabel,
                        "amount": m["totalCharges"],
                        "description": "%s - %s"
                        % (m["contract"]["offer"]["client"]["name"], m["memo"]),
                    }
                )
                break

        total_earning += amt

    list_earning = [round(week_totals[w], 2) for w in x_axis]
    total_earning = round(total_earning, 2)

    tooltip = "'<b>Week : </b>'+this.x+'<br/>'+this.series.name+': $ '+this.y"
    data = {
        "month": month_name[int(month_str)],
        "year": year_str,
        "x_axis": x_axis,
        "report": list_earning,
        "detail_earning": list_report,
        "total_earning": total_earning,
        "charity": round(total_earning * 0.025, 2),
        "title": "Month : %s %s ($ %s)"
        % (month_name[int(month_str)], year_str, total_earning),
        "tooltip": tooltip,
    }
    return data


def timereport_weekly(token, year):
    client = upwork_client.get_client(token)
    current_week = datetime.now().isocalendar()[1] - 1
    if current_week == 0:
        current_week = 1
    last_week = datetime.strptime("%s1231" % year, "%Y%m%d").isocalendar()[1]
    if last_week == 1:
        last_week = 52
    list_week = [str(i) for i in range(1, last_week + 1)]
    query = """query User {
            user {
                freelancerProfile {
                    user {
                        timeReport(timeReportDate_bt: { rangeStart: "%s0101", rangeEnd: "%s1231" }) {
                            dateWorkedOn
                            totalHoursWorked
                        }
                    }
                }
            }
        }
    """ % (
        year,
        year,
    )
    response = graphql.Api(client).execute({"query": query})

    weeks = {}
    total_hours = 0
    weekly_report = []
    earning_report = response["data"]["user"]["freelancerProfile"]["user"]["timeReport"]
    for m in earning_report:
        week_num = datetime.strptime(m["dateWorkedOn"], "%Y-%m-%d").isocalendar()[1]
        if weeks.get(week_num):
            weeks[week_num].append(m["totalHoursWorked"])
        else:
            weeks[week_num] = [m["totalHoursWorked"]]
    for week in list_week:
        if weeks.get(int(week)):
            hours = sum(weeks.get(int(week)))
        else:
            hours = 0
        total_hours += hours
        weekly_report.append(hours)

        selected_year = int(year)
        today = date.today()

        if selected_year == today.year:
            divisor_week = today.isocalendar()[1]
        else:
            divisor_week = last_week

        if divisor_week < 1:
            divisor_week = 1

        avg_week = round(total_hours / divisor_week, 1)

    work_status = "success"
    if avg_week < 20:
        work_status = "danger"
    elif avg_week < 40:
        work_status = "warning"

    tooltip = "'<b>Week '+this.x+'</b><br/>Hour: '+formating_time(this.y)"
    data = {
        "year": year,
        "x_axis": list_week,
        "report": weekly_report,
        "total_hours": int(total_hours),
        "avg_week": avg_week,
        "work_status": work_status,
        "title": "Year : %s" % (year),
        "tooltip": tooltip,
    }
    return data


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _profile_key_from_url(url):
    if not url:
        return None
    s = str(url)
    if "~" in s:
        return "~" + s.split("~", 1)[1].split("/", 1)[0]
    parts = [p for p in s.split("/") if p]
    if parts:
        last = parts[-1]
        if last.startswith("~"):
            return last
    return None


def _extract_client_name(detail):
    def dget(k):
        return _get(detail, k, None)

    for k in ("client_name", "client", "buyer", "team_name", "organization", "company"):
        v = dget(k)
        if v:
            return str(v).strip()

    desc = str(dget("description") or "").strip()
    if not desc:
        return "Unknown"

    m = re.match(r"^(.+?)\s*[-:]\s+.+$", desc)
    if m:
        return m.group(1).strip()

    return "Unknown"


def _normalize_client_name(name: str) -> str:
    cleaned = (name or "").strip()
    cleaned = cleaned.split(">", 1)[0].strip()
    cleaned = re.sub(r"\s*[-:–—]+$", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned or "Unknown"


def _build_total_earning_data(
    request, token, tenant_id, year, month=None, include_detail=False
):
    if month:
        hourly_graph = _cached_earning_graph_monthly(
            request, token, int(year), int(month)
        )
    else:
        hourly_graph = _cached_earning_graph_annually(request, token, str(year))

    start_dt = date(int(year), 1, 1)
    end_dt = date(int(year), 12, 31)
    if month:
        start_dt = date(int(year), int(month), 1)
        end_dt = date(int(year), int(month), monthrange(int(year), int(month))[1])

    freelancer_reference = (
        request.session.get("freelancer_reference")
        or _profile_key_from_url(
            (request.session.get("upwork_auth") or {}).get("profile_url")
        )
        or request.user.username
    )
    fixed_rows = _cached_fixed_price_transactions(
        request,
        token=token,
        freelancer_reference=freelancer_reference,
        tenant_id=tenant_id,
        start_date=start_dt,
        end_date=end_dt,
    )

    fixed_clean = []
    fixed_total = 0.0
    for r in fixed_rows:
        occurred_at = (r.get("occurred_at") or "")[:10]
        amt = float(r.get("amount") or 0.0)
        if amt == 0:
            continue
        client = _normalize_client_name(r.get("client_name") or "Unknown")
        desc = r.get("description") or ""
        fixed_clean.append(
            {
                "date": occurred_at,
                "amount": amt,
                "description": desc,
                "client_name": client,
            }
        )
        fixed_total += amt

    client_totals = defaultdict(float)
    for d in hourly_graph.get("detail_earning") or []:
        client = _normalize_client_name(_extract_client_name(d))
        raw = d.get("amount", 0) or 0
        s = str(raw).replace("$", "").replace(",", "").strip()
        try:
            amount = float(s)
        except ValueError:
            amount = 0.0
        client_totals[client] += amount

    for f in fixed_clean:
        client_totals[f["client_name"]] += float(f["amount"] or 0)

    detail = []
    if include_detail:
        for d in hourly_graph.get("detail_earning") or []:
            detail.append(d)
        for f in fixed_clean:
            detail.append(
                {
                    "date": f["date"],
                    "amount": f["amount"],
                    "description": f'{f.get("client_name") or "Unknown"} - {f.get("description") or ""}',
                    "client_name": f.get("client_name") or "Unknown",
                }
            )
        detail.sort(key=lambda x: x.get("date") or "")

    if month:
        x_axis = hourly_graph.get("x_axis") or []
        hourly_week_totals = {
            x_axis[i]: float(hourly_graph.get("report", [])[i] or 0)
            for i in range(len(x_axis))
        }
        fixed_week_totals = {w: 0.0 for w in x_axis}

        week_ranges = _month_week_ranges(int(year), int(month))
        for item in fixed_clean:
            try:
                d = datetime.strptime(item["date"], "%Y-%m-%d").date()
            except Exception:
                continue
            for wlabel, ws, we in week_ranges:
                if ws <= d <= we:
                    fixed_week_totals[wlabel] += float(item["amount"] or 0)
                    break

        combined_report = [
            round(hourly_week_totals.get(w, 0.0) + fixed_week_totals.get(w, 0.0), 2)
            for w in x_axis
        ]
        total_earning = round(
            float(hourly_graph.get("total_earning") or 0) + fixed_total, 2
        )
        graph = {
            "month": hourly_graph.get("month"),
            "year": str(year),
            "x_axis": x_axis,
            "report": combined_report,
            "detail_earning": detail,
            "total_earning": total_earning,
            "charity": round(total_earning * 0.025, 2),
            "title": "Month : %s %s ($ %s)"
            % (
                hourly_graph.get("month"),
                year,
                total_earning,
            ),
            "tooltip": "'<b>Week : </b>'+this.x+'<br/>'+this.series.name+': $ '+this.y",
        }
    else:
        hourly_monthly = {i: 0.0 for i in range(1, 13)}
        for item in hourly_graph.get("report") or []:
            try:
                idx = int(item.get("month"))
            except Exception:
                continue
            hourly_monthly[idx] = float(item.get("y") or 0)

        fixed_monthly = {i: 0.0 for i in range(1, 13)}
        for item in fixed_clean:
            try:
                d = datetime.strptime(item["date"], "%Y-%m-%d").date()
                fixed_monthly[d.month] += float(item["amount"] or 0)
            except Exception:
                continue

        combined_report = [
            {"y": round(hourly_monthly[i] + fixed_monthly[i], 2), "month": str(i)}
            for i in range(1, 13)
        ]
        total_earning = round(
            float(hourly_graph.get("total_earning") or 0) + fixed_total, 2
        )
        graph = {
            "year": str(year),
            "x_axis": hourly_graph.get("x_axis"),
            "report": combined_report,
            "detail_earning": detail,
            "total_earning": total_earning,
            "charity": round(total_earning * 0.025, 2),
            "title": "Year : %s ($ %s)" % (year, total_earning),
            "tooltip": "'<b>'+this.x+'</b><br/>'+this.series.name+': $ '+this.y",
        }

    total_sum = sum(client_totals.values()) if client_totals else 0.0
    client_rows = [
        {
            "name": name,
            "total": float(total),
            "percent": (float(total) / total_sum * 100.0) if total_sum else 0.0,
        }
        for name, total in sorted(
            client_totals.items(), key=lambda x: x[1], reverse=True
        )
    ]
    client_pie_data = json.dumps(
        [
            {"name": r["name"], "y": float(r["total"])}
            for r in client_rows
            if float(r["total"]) > 0
        ]
    )

    return graph, client_rows, client_pie_data


def earning_graph(request):
    data = {"page_title": "Hourly Graph"}

    year = (
        request.GET.get("year") or request.POST.get("year") or str(datetime.now().year)
    )
    month = request.POST.get("month")

    if not re.match(r"^\d{4}$", str(year)):
        messages.warning(request, "Wrong year format.!")
        return redirect("earning_graph")

    try:
        if month:
            finreport = _cached_earning_graph_monthly(
                request, request.session["token"], int(year), int(month)
            )
        else:
            finreport = _cached_earning_graph_annually(
                request, request.session["token"], str(year)
            )

        data["graph"] = finreport
        graph_obj = data["graph"]
        details = _get(graph_obj, "detail_earning", None) or []

        totals = defaultdict(float)
        for d in details:
            client = _extract_client_name(d)

            raw = _get(d, "amount", 0) or 0
            s = str(raw).replace("$", "").replace(",", "").strip()
            try:
                amount = float(s)
            except ValueError:
                amount = 0.0

            totals[client] += amount

        if len(totals) > 1:
            totals.pop("Unknown", None)

        data["client_rows"] = [
            {"name": name, "total": float(total)}
            for name, total in sorted(totals.items(), key=lambda x: x[1], reverse=True)
        ]

        data["client_pie_data"] = json.dumps(
            [
                {"name": r["name"], "y": float(r["total"])}
                for r in data["client_rows"]
                if float(r["total"]) > 0
            ]
        )
        return render(request, "upworkapi/finance.html", data)

    except InvalidGrantError:
        request.session.pop("token", None)
        messages.warning(request, "Session expired. Please login again.")
        return redirect("auth")

    except KeyError:
        messages.warning(request, "Session missing. Please login again.")
        return redirect("auth")


def total_earning_graph(request, year=None):
    data = {"page_title": "Total Earning"}

    year = (
        request.GET.get("year")
        or request.POST.get("year")
        or (str(year) if year else None)
        or str(datetime.now().year)
    )
    month = request.POST.get("month")

    if not re.match(r"^\d{4}$", str(year)):
        messages.warning(request, "Wrong year format.!")
        return redirect("total_earning_graph")

    token = request.session.get("token")
    tenant_id = request.session.get("tenant_id")
    if not token:
        messages.warning(request, "Missing token. Please login again.")
        return redirect("auth")

    try:
        graph, client_rows, client_pie_data = _build_total_earning_data(
            request=request,
            token=token,
            tenant_id=tenant_id,
            year=year,
            month=month,
            include_detail=bool(month),
        )
        data["graph"] = graph
        data["client_rows"] = client_rows
        data["client_pie_data"] = client_pie_data
    except Exception as exc:
        messages.warning(request, f"Upwork API error: {exc}")
        data["graph"] = _cached_earning_graph_annually(request, token, str(year))
        data["client_rows"] = []
        data["client_pie_data"] = json.dumps([])

    return render(request, "upworkapi/total_earning.html", data)


@login_required(login_url="/")
def all_time_earning_graph(request):
    data = {"page_title": "All Time Earning"}

    token = request.session.get("token")
    tenant_id = request.session.get("tenant_id")
    if not token:
        messages.warning(request, "Missing token. Please login again.")
        return redirect("auth")

    current_year = datetime.now().year
    start_year = 2010
    years = list(range(start_year, current_year + 1))

    totals = []
    client_totals = defaultdict(float)
    try:
        freelancer_reference = (
            request.session.get("freelancer_reference")
            or _profile_key_from_url(
                (request.session.get("upwork_auth") or {}).get("profile_url")
            )
            or request.user.username
        )

        for y in years:
            hourly_graph = _cached_earning_graph_annually(request, token, str(y))
            hourly_total = float(hourly_graph.get("total_earning") or 0)
            for d in hourly_graph.get("detail_earning") or []:
                client = _normalize_client_name(_extract_client_name(d))
                raw = d.get("amount", 0) or 0
                s = str(raw).replace("$", "").replace(",", "").strip()
                try:
                    amount = float(s)
                except ValueError:
                    amount = 0.0
                client_totals[client] += amount

            start_dt = date(y, 1, 1)
            end_dt = date(y, 12, 31)
            fixed_rows = _cached_fixed_price_transactions(
                request,
                token=token,
                freelancer_reference=freelancer_reference,
                tenant_id=tenant_id,
                start_date=start_dt,
                end_date=end_dt,
            )
            fixed_total = 0.0
            for r in fixed_rows:
                amt = float(r.get("amount") or 0.0)
                if amt:
                    fixed_total += amt
                    client = _normalize_client_name(r.get("client_name") or "Unknown")
                    client_totals[client] += amt

            totals.append(round(hourly_total + fixed_total, 2))
    except Exception as exc:
        messages.warning(request, f"Upwork API error: {exc}")
        totals = [0.0 for _ in years]

    first_idx = 0
    for i, total in enumerate(totals):
        if total > 0:
            first_idx = i
            break

    years = years[first_idx:] or years
    totals = totals[first_idx:] or totals

    x_axis = [str(y) for y in years]
    total_earning = round(sum(totals), 2)

    data["graph"] = {
        "x_axis": x_axis,
        "report": totals,
        "total_earning": total_earning,
        "charity": round(total_earning * 0.025, 2),
        "title": "All Time : %s - %s ($ %s)" % (x_axis[0], x_axis[-1], total_earning),
    }

    if len(client_totals) > 1:
        client_totals.pop("Unknown", None)

    total_sum = sum(client_totals.values()) if client_totals else 0.0
    data["client_rows"] = [
        {
            "name": name,
            "total": float(total),
            "percent": (float(total) / total_sum * 100.0) if total_sum else 0.0,
        }
        for name, total in sorted(
            client_totals.items(), key=lambda x: x[1], reverse=True
        )
    ]
    data["client_pie_data"] = json.dumps(
        [
            {"name": r["name"], "y": float(r["total"])}
            for r in data["client_rows"]
            if float(r["total"]) > 0
        ]
    )

    return render(request, "upworkapi/all_time_earning.html", data)


@login_required(login_url="/")
def all_time_earning_year(request, year):
    data = {"page_title": "All Time Earning"}

    if not re.match(r"^\d{4}$", str(year)):
        messages.warning(request, "Wrong year format.!")
        return redirect("all_time_earning_graph")

    token = request.session.get("token")
    tenant_id = request.session.get("tenant_id")
    if not token:
        messages.warning(request, "Missing token. Please login again.")
        return redirect("auth")

    try:
        graph, client_rows, client_pie_data = _build_total_earning_data(
            request=request,
            token=token,
            tenant_id=tenant_id,
            year=year,
            month=None,
            include_detail=False,
        )
        data["graph"] = graph
        data["client_rows"] = client_rows
        data["client_pie_data"] = client_pie_data
    except Exception as exc:
        messages.warning(request, f"Upwork API error: {exc}")
        data["graph"] = earning_graph_annually(token, str(year))
        data["client_rows"] = []
        data["client_pie_data"] = json.dumps([])

    return render(request, "upworkapi/all_time_earning_year.html", data)


@login_required(login_url="/")
def all_time_earning_month(request, year, month):
    data = {"page_title": "All Time Earning"}

    if not re.match(r"^\d{4}$", str(year)):
        messages.warning(request, "Wrong year format.!")
        return redirect("all_time_earning_graph")
    if int(month) < 1 or int(month) > 12:
        messages.warning(request, "Wrong month format.!")
        return redirect("all_time_earning_graph")

    token = request.session.get("token")
    tenant_id = request.session.get("tenant_id")
    if not token:
        messages.warning(request, "Missing token. Please login again.")
        return redirect("auth")

    try:
        graph, client_rows, client_pie_data = _build_total_earning_data(
            request=request,
            token=token,
            tenant_id=tenant_id,
            year=year,
            month=month,
            include_detail=False,
        )
        data["graph"] = graph
        data["client_rows"] = client_rows
        data["client_pie_data"] = client_pie_data
    except Exception as exc:
        messages.warning(request, f"Upwork API error: {exc}")
        data["graph"] = _cached_earning_graph_monthly(
            request, token, int(year), int(month)
        )
        data["client_rows"] = []
        data["client_pie_data"] = json.dumps([])

    return render(request, "upworkapi/all_time_earning_month.html", data)


@login_required(login_url="/")
def fixed_price_graph(request):
    data = {"page_title": "Fixed Price & Bonus"}

    year = request.GET.get("year") or str(datetime.now().year)
    if not re.match(r"^\d{4}$", str(year)):
        messages.warning(request, "Wrong year format.!")
        return redirect("fixed_price_graph")

    start_dt = date(int(year), 1, 1)
    end_dt = date(int(year), 12, 31)

    token = request.session.get("token")
    tenant_id = request.session.get("tenant_id")
    if not token:
        messages.warning(request, "Missing token. Please login again.")
        return redirect("auth")

    debug = False
    try:
        freelancer_reference = (
            request.session.get("freelancer_reference")
            or _profile_key_from_url(
                (request.session.get("upwork_auth") or {}).get("profile_url")
            )
            or request.user.username
        )
        fetch_result = _cached_fixed_price_transactions(
            request,
            token=token,
            freelancer_reference=freelancer_reference,
            tenant_id=tenant_id,
            start_date=start_dt,
            end_date=end_dt,
            debug=debug,
        )
        if debug:
            rows, debug_info = fetch_result
            data["debug_info"] = debug_info
        else:
            rows = fetch_result
    except Exception as exc:
        messages.warning(request, f"Upwork API error: {exc}")
        rows = []
        if debug:
            data["debug_info"] = {"error": str(exc)}

    clean = []
    total = 0.0

    for r in rows:
        occurred_at = (r.get("occurred_at") or "")[:10]
        amt = float(r.get("amount") or 0.0)
        if amt == 0:
            continue

        client = r.get("client_name") or "Unknown"
        kind = r.get("kind") or ""
        desc = r.get("description") or ""

        clean.append(
            {
                "date": occurred_at,
                "client": client,
                "kind": kind,
                "description": desc,
                "amount": amt,
            }
        )
        total += amt

    clean.sort(key=lambda x: x["date"] or "")

    data["year"] = year
    data["rows"] = clean
    data["total"] = round(total, 2)
    data["charity"] = round(total * 0.025, 2)
    data["show_detail_table"] = len(clean) <= 20

    per_client = defaultdict(float)
    for x in clean:
        per_client[x["client"]] += float(x["amount"] or 0)

    data["client_rows"] = [
        {"name": k, "total": round(v, 2)}
        for k, v in sorted(per_client.items(), key=lambda kv: kv[1], reverse=True)
    ]
    data["client_pie_data"] = json.dumps(
        [
            {"name": r["name"], "y": float(r["total"])}
            for r in data["client_rows"]
            if float(r["total"]) > 0
        ]
    )

    monthly = {m: 0.0 for m in range(1, 13)}
    for x in clean:
        try:
            dt = datetime.strptime(x["date"], "%Y-%m-%d").date()
            monthly[dt.month] += float(x["amount"] or 0)
        except Exception:
            pass

    data["x_axis"] = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    data["report"] = [{"y": round(monthly[i], 2), "month": i} for i in range(1, 13)]
    data["tooltip"] = "'<b>'+this.x+'</b><br/>$ '+this.y"

    return render(request, "upworkapi/fixed_price.html", data)


@login_required(login_url="/")
def fixed_price_month_detail(request, year, month):
    data = {"page_title": "Fixed Price & Bonus"}

    if not re.match(r"^\d{4}$", str(year)):
        messages.warning(request, "Wrong year format.!")
        return redirect("fixed_price_graph")

    if int(month) < 1 or int(month) > 12:
        messages.warning(request, "Wrong month format.!")
        return redirect("fixed_price_graph")

    start_dt = date(int(year), int(month), 1)
    end_dt = date(int(year), int(month), monthrange(int(year), int(month))[1])

    token = request.session.get("token")
    tenant_id = request.session.get("tenant_id")
    if not token:
        messages.warning(request, "Missing token. Please login again.")
        return redirect("auth")

    try:
        freelancer_reference = (
            request.session.get("freelancer_reference")
            or _profile_key_from_url(
                (request.session.get("upwork_auth") or {}).get("profile_url")
            )
            or request.user.username
        )
        rows = _cached_fixed_price_transactions(
            request,
            token=token,
            freelancer_reference=freelancer_reference,
            tenant_id=tenant_id,
            start_date=start_dt,
            end_date=end_dt,
        )
    except Exception as exc:
        messages.warning(request, f"Upwork API error: {exc}")
        rows = []

    clean = []
    total = 0.0

    for r in rows:
        occurred_at = (r.get("occurred_at") or "")[:10]
        amt = float(r.get("amount") or 0.0)
        if amt == 0:
            continue

        client = r.get("client_name") or r.get("client") or "Unknown"
        kind = r.get("kind") or ""
        desc = r.get("description") or ""

        clean.append(
            {
                "date": occurred_at,
                "client": client,
                "kind": kind,
                "description": desc,
                "amount": amt,
            }
        )
        total += amt

    clean.sort(key=lambda x: x["date"] or "")

    month_label = calendar.month_name[int(month)]

    week_ranges = _month_week_ranges(int(year), int(month))
    x_axis = [wlabel for (wlabel, _, _) in week_ranges]
    week_totals = {wlabel: 0.0 for wlabel in x_axis}

    for item in clean:
        try:
            d = datetime.strptime(item["date"], "%Y-%m-%d").date()
        except Exception:
            continue
        for wlabel, ws, we in week_ranges:
            if ws <= d <= we:
                week_totals[wlabel] += float(item["amount"] or 0)
                break

    detail_rows = []
    for item in clean:
        detail_rows.append(
            {
                "date": item["date"],
                "description": f'{item["client"]} - {item["description"]}',
                "amount": item["amount"],
            }
        )

    graph = {
        "month": month_label,
        "year": str(year),
        "x_axis": x_axis,
        "report": [round(week_totals[w], 2) for w in x_axis],
        "detail_earning": detail_rows,
        "total_earning": round(total, 2),
        "charity": round(total * 0.025, 2),
        "title": "Month : %s %s ($ %s)"
        % (
            month_label,
            year,
            round(total, 2),
        ),
        "tooltip": "'<b>Week : </b>'+this.x+'<br/>'+this.series.name+': $ '+this.y",
    }
    data["graph"] = graph

    per_client = defaultdict(float)
    for item in clean:
        per_client[item["client"]] += float(item["amount"] or 0)

    data["client_rows"] = [
        {"name": k, "total": round(v, 2)}
        for k, v in sorted(per_client.items(), key=lambda kv: kv[1], reverse=True)
    ]
    data["client_pie_data"] = json.dumps(
        [
            {"name": r["name"], "y": float(r["total"])}
            for r in data["client_rows"]
            if float(r["total"]) > 0
        ]
    )

    return render(request, "upworkapi/fixed_price_month_detail.html", data)


@login_required(login_url="/")
def timereport_graph(request):
    data = {"page_title": "Time Report Graph"}

    if request.method == "POST":
        year = request.POST.get("year")
        if not re.match("^[0-9]+$", year) or len(year) != 4:
            messages.warning(request, "Wrong year format.!")
            return redirect("timereport_graph")
    else:
        now = datetime.now()
        year = str(now.year)

    timelog = timereport_weekly(request.session["token"], year)
    data["graph"] = timelog
    return render(request, "upworkapi/timereport.html", data)


@login_required(login_url="/")
def earning_month_client_detail(request, year, month, client_name):
    finreport = earning_graph_monthly(request.session["token"], int(year), int(month))

    rows = []
    total = 0.0

    for d in finreport.get("detail_earning") or []:
        client = _extract_client_name(d)
        if client == client_name:
            rows.append(d)
            total += float(_get(d, "amount", 0) or 0)

    return render(
        request,
        "earning/earning_month_client_detail.html",
        {
            "year": year,
            "month": month,
            "client_name": client_name,
            "rows": rows,
            "total": total,
        },
    )
