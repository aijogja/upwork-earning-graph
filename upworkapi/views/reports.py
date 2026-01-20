from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from upworkapi.utils import upwork_client
from datetime import datetime
from calendar import monthrange, month_name
from upwork.routers import graphql
from datetime import datetime, timedelta
import re
from datetime import date
from oauthlib.oauth2 import InvalidGrantError
from django.shortcuts import render
from django.db.models import Sum
from django.db.models.functions import Coalesce
from decimal import Decimal
from collections import defaultdict
import calendar
import json
from upworkapi.services.transactions import fetch_fixed_price_transactions



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

    list_month = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

    start_date = f"{year}0101"
    end_date   = f"{year}1231"

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
    }""" % (start_date, end_date)

    response = graphql.Api(client).execute({"query": query})
    rows = response["data"]["user"]["freelancerProfile"]["user"]["timeReport"]

    # monthly totals
    month_totals = {i: 0.0 for i in range(1, 13)}
    total_earning = 0.0

    # IMPORTANT: yearly detail_earning for pie aggregation
    detail = []

    for r in rows:
        dt = datetime.strptime(r["dateWorkedOn"], "%Y-%m-%d").date()
        amt = float((r.get("totalCharges") or 0) or 0)

        month_totals[dt.month] += amt
        total_earning += amt

        client_name = (
            (((r.get("contract") or {}).get("offer") or {}).get("client") or {}).get("name")
            or "Unknown"
        )

        memo = r.get("memo") or ""
        detail.append({
            "date": r["dateWorkedOn"],
            "month": str(dt.month),
            "amount": r.get("totalCharges") or 0,
            "description": f"{client_name} - {memo}",
            "client_name": client_name,
        })

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
    """ % (start_date, end_date)

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

        for (wlabel, ws, we) in week_ranges:
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
        "title": "Month : %s %s ($ %s)" % (month_name[int(month_str)], year_str, total_earning),
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


@login_required(login_url="/")
def _extract_client_name(detail):
    for attr in ("client_name", "client", "buyer", "team_name", "organization", "company"):
        val = getattr(detail, attr, None)
        if val:
            return str(val).strip()

    desc = str(getattr(detail, "description", "")).strip()
    if not desc:
        return "Unknown"

    m = re.match(r"^(.+?)\s*[-:]\s+.+$", desc)
    if m:
        return m.group(1).strip()

    return "Unknown"

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

def earning_graph(request):
    data = {"page_title": "Earning Graph"}

    year = request.GET.get("year") or request.POST.get("year") or str(datetime.now().year)
    month = request.POST.get("month")

    if not re.match(r"^\d{4}$", str(year)):
        messages.warning(request, "Wrong year format.!")
        return redirect("earning_graph")

    try:
        if month:
            finreport = earning_graph_monthly(
                request.session["token"], int(year), int(month)
            )
        else:
            finreport = earning_graph_annually(
                request.session["token"], str(year)
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

        data["client_pie_data"] = json.dumps([
            {"name": r["name"], "y": float(r["total"])}
            for r in data["client_rows"]
            if float(r["total"]) > 0
        ])
        return render(request, "upworkapi/finance.html", data)

    except InvalidGrantError:
        request.session.pop("token", None)
        messages.warning(request, "Session expired. Please login again.")
        return redirect("auth")

    except KeyError:
    
        messages.warning(request, "Session missing. Please login again.")
        return redirect("auth")

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
            or _profile_key_from_url((request.session.get("upwork_auth") or {}).get("profile_url"))
            or request.user.username
        )
        fetch_result = fetch_fixed_price_transactions(
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

        clean.append({
            "date": occurred_at,
            "client": client,
            "kind": kind,
            "description": desc,
            "amount": amt,
        })
        total += amt


    clean.sort(key=lambda x: x["date"] or "")

    data["year"] = year
    data["rows"] = clean
    data["total"] = round(total, 2)
    data["show_detail_table"] = len(clean) <= 20


    per_client = defaultdict(float)
    for x in clean:
        per_client[x["client"]] += float(x["amount"] or 0)

    data["client_rows"] = [
        {"name": k, "total": round(v, 2)}
        for k, v in sorted(per_client.items(), key=lambda kv: kv[1], reverse=True)
    ]
    data["client_pie_data"] = json.dumps([
        {"name": r["name"], "y": float(r["total"])}
        for r in data["client_rows"]
        if float(r["total"]) > 0
    ])


    monthly = {m: 0.0 for m in range(1, 13)}
    for x in clean:
        try:
            dt = datetime.strptime(x["date"], "%Y-%m-%d").date()
            monthly[dt.month] += float(x["amount"] or 0)
        except Exception:
            pass

    data["x_axis"] = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    data["report"] = [
        {"y": round(monthly[i], 2), "month": i}
        for i in range(1, 13)
    ]
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
            or _profile_key_from_url((request.session.get("upwork_auth") or {}).get("profile_url"))
            or request.user.username
        )
        rows = fetch_fixed_price_transactions(
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

        clean.append({
            "date": occurred_at,
            "client": client,
            "kind": kind,
            "description": desc,
            "amount": amt,
        })
        total += amt

    clean.sort(key=lambda x: x["date"] or "")

    month_name = calendar.month_name[int(month)]

    week_ranges = _month_week_ranges(int(year), int(month))
    x_axis = [wlabel for (wlabel, _, _) in week_ranges]
    week_totals = {wlabel: 0.0 for wlabel in x_axis}

    for item in clean:
        try:
            d = datetime.strptime(item["date"], "%Y-%m-%d").date()
        except Exception:
            continue
        for (wlabel, ws, we) in week_ranges:
            if ws <= d <= we:
                week_totals[wlabel] += float(item["amount"] or 0)
                break

    detail_rows = []
    for item in clean:
        detail_rows.append({
            "date": item["date"],
            "description": f'{item["client"]} - {item["description"]}',
            "amount": item["amount"],
        })

    graph = {
        "month": month_name,
        "year": str(year),
        "x_axis": x_axis,
        "report": [round(week_totals[w], 2) for w in x_axis],
        "detail_earning": detail_rows,
        "total_earning": round(total, 2),
        "charity": round(total * 0.025, 2),
        "title": "Month : %s %s ($ %s)" % (
            month_name,
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
    data["client_pie_data"] = json.dumps([
        {"name": r["name"], "y": float(r["total"])}
        for r in data["client_rows"]
        if float(r["total"]) > 0
    ])

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
    qs = (
        Earning.objects
        .filter(date__year=year, date__month=month, client_name=client_name)
        .order_by("date")
    )

    total = qs.aggregate(total=Coalesce(Sum("amount"), Decimal("0.0")))["total"]

    return render(
        request,
        "earning/earning_month_client_detail.html",
        {
            "year": year,
            "month": month,
            "client_name": client_name,
            "rows": qs,
            "total": float(total),
        },
    )

def _extract_client_name(detail):
    for attr in ("client_name", "client", "buyer", "team_name", "organization", "company"):
        val = getattr(detail, attr, None)
        if val:
            return str(val).strip()

    desc = str(getattr(detail, "description", "")).strip()
    if not desc:
        return "Unknown"

    m = re.match(r"^([^:-]{2,60})\s*[:\-]\s+.+$", desc)
    if m:
        return m.group(1).strip()

    return desc[:40]

@login_required(login_url="/")
def earning_month_client_detail(request, year, month, client_name):
    finreport = earning_graph_monthly(request.session["token"], int(year), int(month))

    rows = []
    total = 0.0

    if getattr(finreport, "detail_earning", None):
        for d in finreport.detail_earning:
            client = _extract_client_name(d)
            if client == client_name:
                rows.append(d)
                total += float(getattr(d, "amount", 0) or 0)

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

def _extract_client_name(detail):
    desc = str(_get(detail, "description", "") or "").strip()
    if not desc:
        return "Unknown"

    return desc.split(" - ", 1)[0].strip() or "Unknown"
