from calendar import month_name, monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
import calendar
import json
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import redirect, render
from oauthlib.oauth2 import InvalidGrantError
from upwork.routers import graphql

from upworkapi.services.transactions import (
    fetch_fixed_price_transactions,
    fetch_service_fee_history,
    fetch_transaction_history_rows,
)
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


def _cached_timereport_year(request, token, year):
    key = _cache_key("timereport_year", request.user.id, year)
    cached = cache.get(key)
    if cached is not None:
        return cached
    data = timereport_weekly(token, year)
    cache.set(key, data, CACHE_TTL_SECONDS)
    return data


def _cached_fixed_price_transactions(
    request,
    *,
    token,
    freelancer_reference,
    tenant_id,
    tenant_ids=None,
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

    tenant_ids_part = None
    if tenant_ids:
        tenant_ids_part = ",".join(sorted(str(t) for t in tenant_ids if t))
    key = _cache_key(
        "fixed_tx",
        request.user.id,
        tenant_id or "",
        tenant_ids_part,
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
        tenant_ids=tenant_ids,
        start_date=start_date,
        end_date=end_date,
        debug=debug,
    )
    cache.set(key, rows, CACHE_TTL_SECONDS)
    return rows


def _cached_hourly_service_fees(
    request,
    *,
    token,
    tenant_id,
    tenant_ids=None,
    start_date,
    end_date,
):
    tenant_key = ""
    if tenant_ids:
        tenant_key = ",".join(sorted(str(t) for t in tenant_ids if str(t)))
    key = _cache_key(
        "hourly_service_fee",
        request.user.id,
        tenant_key or (tenant_id or ""),
        _date_key(start_date),
        _date_key(end_date),
    )
    cached = cache.get(key)
    if cached is not None:
        return cached

    rows = fetch_service_fee_history(
        token=token,
        tenant_id=tenant_id,
        tenant_ids=tenant_ids,
        start_date=start_date,
        end_date=end_date,
    )
    cache.set(key, rows, CACHE_TTL_SECONDS)
    return rows


def _service_fee_summary(
    request,
    *,
    start_date,
    end_date,
    include_rows=False,
    debug=False,
):
    result = fetch_service_fee_history(
        token=request.session.get("token"),
        tenant_id=request.session.get("tenant_id"),
        tenant_ids=request.session.get("tenant_ids"),
        start_date=start_date,
        end_date=end_date,
        debug=debug,
    )
    if debug:
        rows, debug_info = result
    else:
        rows = result
        debug_info = None
    rows = rows or []
    rows.sort(key=lambda x: x.get("date") or x.get("occurred_at") or "")
    for row in rows:
        row["display_date"] = _display_date_str(
            row.get("date") or row.get("occurred_at") or ""
        )
        row["client_name"] = _normalize_client_name(_extract_client_name(row))
    total = sum(float(r.get("amount") or 0) for r in rows)
    if not include_rows:
        rows = []
    return rows, total, debug_info


def _is_txn_fee_row(row) -> bool:
    text = f"{row.get('kind') or ''} {row.get('subtype') or ''} {row.get('description') or ''} {row.get('description_ui') or ''}".lower()
    if "connect" in text or "membership" in text or "subscription" in text:
        return False
    if "service fee" in text or "upwork fee" in text or "marketplace fee" in text:
        return True
    if "service_fee" in text or "upwork_fee" in text:
        return True
    if "fee" in text:
        amt = float(row.get("amount") or 0)
        return amt < 0
    return False


def _is_txn_earning_row(row) -> bool:
    if _is_txn_fee_row(row):
        return False
    amt = float(row.get("amount") or 0)
    if amt <= 0:
        return False
    text = f"{row.get('kind') or ''} {row.get('subtype') or ''} {row.get('description') or ''} {row.get('description_ui') or ''}".lower()
    if "apinvoice" in text or "hourly" in text:
        return True
    for key in ("fixed", "bonus", "milestone"):
        if key in text:
            return True
    return False


def _is_txn_membership_row(row) -> bool:
    text = f"{row.get('subtype') or ''} {row.get('description') or ''} {row.get('description_ui') or ''}".lower()
    if "connect" in text:
        return False
    if "subscription" in text:
        return True
    if "membership" in text or "freelancer plus" in text:
        return True
    return False


def _is_txn_connects_row(row) -> bool:
    text = f"{row.get('subtype') or ''} {row.get('description') or ''} {row.get('description_ui') or ''}".lower()
    if "connect" in text or "connects" in text:
        return True
    return "fees for additional connects" in text


def _is_txn_fixed_bonus_context(row) -> bool:
    text = f"{row.get('subtype') or ''} {row.get('description') or ''} {row.get('description_ui') or ''}".lower()
    for key in ("fixed", "bonus", "milestone", "escrow"):
        if key in text:
            return True
    return False


def _parse_txn_date(row) -> date | None:
    raw = row.get("date") or row.get("occurred_at")
    if not raw:
        return None
    s = str(raw)
    if len(s) >= 10:
        s = s[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_txn_work_range(row) -> tuple[date | None, date | None]:
    text = f"{row.get('description_ui') or ''} {row.get('description') or ''}"
    patterns = [
        (r"(\\d{2}/\\d{2}/\\d{4})\\s*-\\s*(\\d{2}/\\d{2}/\\d{4})", ["%m/%d/%Y"]),
        (r"(\\d{4}-\\d{2}-\\d{2})\\s*-\\s*(\\d{4}-\\d{2}-\\d{2})", ["%Y-%m-%d"]),
        (
            r"([A-Za-z]{3,9}\\s+\\d{1,2},\\s+\\d{4})\\s*-\\s*([A-Za-z]{3,9}\\s+\\d{1,2},\\s+\\d{4})",
            ["%b %d, %Y", "%B %d, %Y"],
        ),
        (
            r"(\\d{1,2}\\s+[A-Za-z]{3,9}\\s+\\d{4})\\s*-\\s*(\\d{1,2}\\s+[A-Za-z]{3,9}\\s+\\d{4})",
            ["%d %b %Y", "%d %B %Y"],
        ),
        (
            r"(\\d{2}-[A-Za-z]{3}-\\d{4})\\s*-\\s*(\\d{2}-[A-Za-z]{3}-\\d{4})",
            ["%d-%b-%Y"],
        ),
    ]

    def _parse_with_formats(value: str, formats: list[str]) -> date | None:
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt).date()
            except Exception:
                continue
        return None

    for pattern, formats in patterns:
        m = re.search(pattern, text)
        if not m:
            continue
        start_dt = _parse_with_formats(m.group(1), formats)
        end_dt = _parse_with_formats(m.group(2), formats)
        if start_dt and end_dt:
            return start_dt, end_dt
    return None, None


def _effective_txn_date(row, *, year: int, month: int) -> date | None:
    start_dt, end_dt = _parse_txn_work_range(row)
    if end_dt and end_dt.year == year and end_dt.month == month:
        return end_dt
    if start_dt and start_dt.year == year and start_dt.month == month:
        return start_dt
    return _parse_txn_date(row)


def _effective_txn_date_any(row) -> date | None:
    start_dt, end_dt = _parse_txn_work_range(row)
    if end_dt:
        return end_dt
    if start_dt:
        return start_dt
    return _parse_txn_date(row)


def _display_date(value: date | None, fallback: str = "") -> str:
    if not value:
        return fallback
    return value.strftime("%d-%m-%Y")


def _display_date_str(value: str) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%d-%b-%Y",
        "%d-%m-%Y",
    ):
        try:
            return datetime.strptime(s, fmt).strftime("%d-%m-%Y")
        except Exception:
            continue
    return s


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
                "date": _display_date(dt, fallback=r["dateWorkedOn"]),
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
    first_day = date(year, month, 1)
    last_day = date(year, month, count_day)
    # Query a padded range and filter by dateWorkedOn to avoid missing edge data.
    query_start = first_day - timedelta(days=7)
    query_end = last_day + timedelta(days=7)
    start_date = query_start.strftime("%Y%m%d")
    end_date = query_end.strftime("%Y%m%d")

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
    filtered_report = []
    for r in earning_report:
        try:
            d = datetime.strptime(r["dateWorkedOn"], "%Y-%m-%d").date()
        except Exception:
            continue
        if d.year == year and d.month == month:
            filtered_report.append(r)
    earning_report = filtered_report

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
                contract = m.get("contract") or {}
                client_name = ((contract.get("offer") or {}).get("client") or {}).get(
                    "name"
                ) or "Unknown"
                list_report.append(
                    {
                        "date": _display_date(d, fallback=m["dateWorkedOn"]),
                        "week": wlabel,
                        "amount": m["totalCharges"],
                        "description": "%s - %s" % (client_name, m["memo"]),
                        "client_name": client_name,
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
                            contract {
                                offer {
                                    client { name }
                                }
                            }
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
    total_hours = 0.0
    weekly_report = []
    earning_report = response["data"]["user"]["freelancerProfile"]["user"]["timeReport"]
    per_client = defaultdict(float)
    min_date = None
    max_date = None
    raw_total_hours = 0.0
    for m in earning_report:
        try:
            d = datetime.strptime(m["dateWorkedOn"], "%Y-%m-%d").date()
            if min_date is None or d < min_date:
                min_date = d
            if max_date is None or d > max_date:
                max_date = d
        except Exception:
            d = None
        week_num = datetime.strptime(m["dateWorkedOn"], "%Y-%m-%d").isocalendar()[1]
        raw_total_hours += float(m.get("totalHoursWorked") or 0)
        if weeks.get(week_num):
            weeks[week_num].append(m["totalHoursWorked"])
        else:
            weeks[week_num] = [m["totalHoursWorked"]]
        client_name = (
            ((m.get("contract") or {}).get("offer") or {}).get("client") or {}
        ).get("name") or "Unknown"
        per_client[_normalize_client_name(client_name)] += float(
            m.get("totalHoursWorked") or 0
        )
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
    client_rows = [
        {"name": k, "total": round(v, 2)}
        for k, v in sorted(per_client.items(), key=lambda kv: kv[1], reverse=True)
    ]
    client_pie_data = json.dumps(
        [{"name": r["name"], "y": float(r["total"])} for r in client_rows if r["total"]]
    )

    total_hours = round(total_hours, 2)
    total_hours = round(total_hours, 2)
    raw_total_hours = round(raw_total_hours, 2)
    data = {
        "year": year,
        "x_axis": list_week,
        "report": weekly_report,
        "total_hours": total_hours,
        "avg_week": avg_week,
        "work_status": work_status,
        "title": "Year : %s" % (year),
        "tooltip": tooltip,
        "client_rows": client_rows,
        "client_pie_data": client_pie_data,
        "row_count": len(earning_report),
        "raw_total_hours": raw_total_hours,
        "min_date": min_date.isoformat() if min_date else None,
        "max_date": max_date.isoformat() if max_date else None,
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

    for sep in (" - ", " -", " – ", " — ", ": "):
        if sep in desc:
            left = desc.split(sep, 1)[0].strip()
            if left:
                return left

    m = re.match(r"^(.+?)\s*[-:]\s*.*$", desc)
    if m:
        left = m.group(1).strip()
        if left:
            return left

    return "Unknown"


def _normalize_client_name(name: str) -> str:
    cleaned = (name or "").strip()
    cleaned = cleaned.split(">", 1)[0].strip()
    cleaned = re.sub(r"\s*[-:–—]+$", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned or "Unknown"


def _client_from_detail(detail):
    client = _get(detail, "client_name")
    if not client or str(client).strip().lower() == "unknown":
        client = _extract_client_name(detail)
    return _normalize_client_name(client)


def _client_from_fixed(detail):
    client = _get(detail, "client_name") or _get(detail, "client")
    if not client or str(client).strip().lower() == "unknown":
        client = _get(detail, "description") or "Unknown"
    return _normalize_client_name(client)


def _is_excluded_client_label(detail, client_name: str) -> bool:
    text = f"{client_name or ''} {_get(detail, 'description', '') or ''}".lower()
    if "fees for additional connects" in text:
        return True
    if "fees for freelancer plus membership" in text:
        return True
    if "fees for agency plus membership" in text:
        return True
    if "subscription renewal charges" in text:
        return True
    if "payment - paypal nomorcantikxplor@yahoo.com" in text:
        return True
    return False


def _accumulate_client_totals(client_totals, details):
    for d in details:
        client = _client_from_detail(d)
        if _is_excluded_client_label(d, client):
            continue
        raw = _get(d, "amount", 0) or 0
        s = str(raw).replace("$", "").replace(",", "").strip()
        try:
            amount = float(s)
        except ValueError:
            amount = 0.0
        client_totals[client] += amount


def _amount_from_detail(detail) -> float:
    raw = _get(detail, "amount", 0) or 0
    s = str(raw).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


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
        tenant_ids=request.session.get("tenant_ids"),
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
        display_date = _display_date_str(occurred_at)
        client = _normalize_client_name(r.get("client_name") or "Unknown")
        desc = r.get("description") or ""
        fixed_clean.append(
            {
                "date": occurred_at,
                "display_date": display_date or occurred_at,
                "amount": amt,
                "description": desc,
                "client_name": client,
            }
        )
        fixed_total += amt

    client_totals = defaultdict(float)
    _accumulate_client_totals(client_totals, hourly_graph.get("detail_earning") or [])
    for f in fixed_clean:
        client = _client_from_fixed(f)
        if _is_excluded_client_label(f, client):
            continue
        client_totals[client] += float(f["amount"] or 0)

    detail = []
    if include_detail:
        for d in hourly_graph.get("detail_earning") or []:
            detail.append(d)
        for f in fixed_clean:
            detail.append(
                {
                    "date": f.get("display_date") or _display_date_str(f["date"]),
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
    data["service_fee_rows"] = []
    data["service_fee_total"] = 0.0

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
        _accumulate_client_totals(totals, details)

        for d in details:
            client_name = _normalize_client_name(_extract_client_name(d))
            d["client"] = client_name

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
        if graph_obj.get("month"):
            start_dt = date(int(year), int(month), 1)
            end_dt = date(int(year), int(month), monthrange(int(year), int(month))[1])
            fee_rows, fee_total, _fee_debug = _service_fee_summary(
                request,
                start_date=start_dt,
                end_date=end_dt,
                include_rows=True,
                debug=False,
            )
            data["service_fee_rows"] = fee_rows
            data["service_fee_total"] = fee_total
        else:
            start_dt = date(int(year), 1, 1)
            end_dt = date(int(year), 12, 31)
            _, fee_total, _fee_debug = _service_fee_summary(
                request,
                start_date=start_dt,
                end_date=end_dt,
                include_rows=False,
                debug=False,
            )
            data["service_fee_total"] = fee_total
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
    data["service_fee_total"] = 0.0
    data["service_fee_rows"] = []

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
        if month:
            start_dt = date(int(year), int(month), 1)
            end_dt = date(int(year), int(month), monthrange(int(year), int(month))[1])
            fee_rows, fee_total, fee_debug = _service_fee_summary(
                request,
                start_date=start_dt,
                end_date=end_dt,
                include_rows=True,
                debug=True,
            )
            data["service_fee_rows"] = fee_rows
            data["service_fee_total"] = fee_total
            data["service_fee_debug"] = fee_debug
        else:
            start_dt = date(int(year), 1, 1)
            end_dt = date(int(year), 12, 31)
            _, fee_total, fee_debug = _service_fee_summary(
                request,
                start_date=start_dt,
                end_date=end_dt,
                include_rows=False,
                debug=True,
            )
            data["service_fee_total"] = fee_total
            data["service_fee_debug"] = fee_debug
    except Exception as exc:
        messages.warning(request, f"Upwork API error: {exc}")
        data["graph"] = _cached_earning_graph_annually(request, token, str(year))
        data["client_rows"] = []
        data["client_pie_data"] = json.dumps([])

    return render(request, "upworkapi/total_earning.html", data)


def total_earning_graph_trx(request):
    data = {"page_title": "Total Earning"}
    data["service_fee_total"] = 0.0
    data["service_fee_rows"] = []
    data["membership_rows"] = []
    data["connect_rows"] = []
    data["membership_total"] = 0.0
    data["connect_total"] = 0.0

    year = (
        request.GET.get("year") or request.POST.get("year") or str(datetime.now().year)
    )
    month = request.POST.get("month")
    net_view = request.GET.get("net") == "1"

    if not re.match(r"^\d{4}$", str(year)):
        messages.warning(request, "Wrong year format.!")
        return redirect("total_earning_graph")

    token = request.session.get("token")
    if not token:
        messages.warning(request, "Missing token. Please login again.")
        return redirect("auth")

    if month:
        start_dt = date(int(year), int(month), 1)
        end_dt = date(int(year), int(month), monthrange(int(year), int(month))[1])
        query_start_dt = start_dt - timedelta(days=14)
        query_end_dt = end_dt + timedelta(days=14)
    else:
        start_dt = date(int(year), 1, 1)
        end_dt = date(int(year), 12, 31)
        query_start_dt = start_dt
        query_end_dt = end_dt

    rows, debug_info = fetch_transaction_history_rows(
        token=token,
        tenant_id=request.session.get("tenant_id"),
        tenant_ids=request.session.get("tenant_ids"),
        start_date=query_start_dt,
        end_date=query_end_dt,
        debug=True,
    )
    rows = rows or []

    earning_rows = [r for r in rows if _is_txn_earning_row(r)]
    fee_rows = [r for r in rows if _is_txn_fee_row(r)]
    membership_rows = [r for r in rows if _is_txn_membership_row(r)]
    connect_rows = [r for r in rows if _is_txn_connects_row(r)]

    period_earning_rows = []
    period_fee_rows = []
    if month:
        for row in earning_rows:
            d = _effective_txn_date(row, year=int(year), month=int(month))
            if d and d.year == int(year) and d.month == int(month):
                period_earning_rows.append(row)
        for row in fee_rows:
            d = _effective_txn_date(row, year=int(year), month=int(month))
            if d and d.year == int(year) and d.month == int(month):
                period_fee_rows.append(row)
        for row in membership_rows:
            d = _effective_txn_date(row, year=int(year), month=int(month))
            if d and d.year == int(year) and d.month == int(month):
                data["membership_rows"].append(row)
        for row in connect_rows:
            d = _effective_txn_date(row, year=int(year), month=int(month))
            if d and d.year == int(year) and d.month == int(month):
                data["connect_rows"].append(row)
    else:
        for row in earning_rows:
            d = _effective_txn_date_any(row)
            if d and d.year == int(year):
                period_earning_rows.append(row)
        for row in fee_rows:
            d = _effective_txn_date_any(row)
            if d and d.year == int(year):
                period_fee_rows.append(row)
        for row in membership_rows:
            d = _effective_txn_date_any(row)
            if d and d.year == int(year):
                data["membership_rows"].append(row)
        for row in connect_rows:
            d = _effective_txn_date_any(row)
            if d and d.year == int(year):
                data["connect_rows"].append(row)

    period_fee_rows.sort(key=lambda x: x.get("date") or x.get("occurred_at") or "")
    data["membership_rows"].sort(
        key=lambda x: x.get("date") or x.get("occurred_at") or ""
    )
    data["connect_rows"].sort(key=lambda x: x.get("date") or x.get("occurred_at") or "")

    for row in period_fee_rows:
        d = _parse_txn_date(row)
        row["display_date"] = _display_date(
            d, fallback=str(row.get("date") or row.get("occurred_at") or "")
        )
        if row.get("display_date") == (row.get("date") or row.get("occurred_at")):
            row["display_date"] = _display_date_str(
                row.get("date") or row.get("occurred_at") or ""
            )
    for row in data["membership_rows"]:
        d = _parse_txn_date(row)
        row["display_date"] = _display_date(
            d, fallback=str(row.get("date") or row.get("occurred_at") or "")
        )
        if row.get("display_date") == (row.get("date") or row.get("occurred_at")):
            row["display_date"] = _display_date_str(
                row.get("date") or row.get("occurred_at") or ""
            )
    for row in data["connect_rows"]:
        d = _parse_txn_date(row)
        row["display_date"] = _display_date(
            d, fallback=str(row.get("date") or row.get("occurred_at") or "")
        )
        if row.get("display_date") == (row.get("date") or row.get("occurred_at")):
            row["display_date"] = _display_date_str(
                row.get("date") or row.get("occurred_at") or ""
            )
    fee_total = sum(float(r.get("amount") or 0) for r in period_fee_rows)
    membership_total = sum(float(r.get("amount") or 0) for r in data["membership_rows"])
    connect_total = sum(float(r.get("amount") or 0) for r in data["connect_rows"])

    data["service_fee_total"] = fee_total
    data["membership_total"] = membership_total
    data["connect_total"] = connect_total
    data["membership_total_display"] = -abs(membership_total)
    data["connect_total_display"] = -abs(connect_total)
    data["misc_total_display"] = -abs(membership_total + connect_total)
    if month:
        data["service_fee_rows"] = period_fee_rows
    data["service_fee_debug"] = debug_info

    data["membership_connect_rows"] = []
    for row in data["membership_rows"]:
        data["membership_connect_rows"].append(
            {
                "display_date": row.get("display_date"),
                "type": "Membership",
                "description": row.get("description_ui")
                or row.get("description")
                or "",
                "amount": -abs(float(row.get("amount") or 0)),
            }
        )
    for row in data["connect_rows"]:
        data["membership_connect_rows"].append(
            {
                "display_date": row.get("display_date"),
                "type": "Connects",
                "description": row.get("description_ui")
                or row.get("description")
                or "",
                "amount": -abs(float(row.get("amount") or 0)),
            }
        )
    data["membership_connect_rows"].sort(key=lambda x: x.get("display_date") or "")
    data["show_membership_connects"] = bool(
        data["membership_rows"] or data["connect_rows"]
    )

    if month:
        week_ranges = _month_week_ranges(int(year), int(month))
        x_axis = [wlabel for (wlabel, _, _) in week_ranges]
        week_totals = {wlabel: 0.0 for wlabel in x_axis}
        fee_week_totals = {wlabel: 0.0 for wlabel in x_axis}

        for row in period_earning_rows:
            d = _effective_txn_date(row, year=int(year), month=int(month))
            if not d:
                continue
            if d.year != int(year) or d.month != int(month):
                continue
            for wlabel, ws, we in week_ranges:
                if ws <= d <= we:
                    week_totals[wlabel] += float(row.get("amount") or 0)
                    break

        for row in period_fee_rows:
            d = _parse_txn_date(row)
            if not d:
                continue
            if d.year != int(year) or d.month != int(month):
                continue
            for wlabel, ws, we in week_ranges:
                if ws <= d <= we:
                    fee_week_totals[wlabel] += float(row.get("amount") or 0)
                    break

        report = []
        detail_rows = []
        for wlabel in x_axis:
            gross = round(week_totals[wlabel], 2)
            fee = round(fee_week_totals[wlabel], 2)
            net = round(gross + fee, 2)
            report.append(net if net_view else gross)

        for row in period_earning_rows:
            d = _effective_txn_date(row, year=int(year), month=int(month))
            if not d:
                continue
            if d.year != int(year) or d.month != int(month):
                continue
            week_label = ""
            for wlabel, ws, we in week_ranges:
                if ws <= d <= we:
                    week_label = wlabel
                    break
            if not week_label:
                week_label = f"W{((d.day - 1) // 7) + 1}"
            detail_rows.append(
                {
                    "week": week_label,
                    "date": _display_date(d, fallback=d.strftime("%Y-%m-%d")),
                    "client_name": row.get("client_name") or "Unknown",
                    "description": row.get("description_ui")
                    or row.get("description")
                    or "",
                    "amount": float(row.get("amount") or 0),
                }
            )
        detail_rows.sort(key=lambda x: x.get("date") or "")

        total_gross = round(sum(week_totals.values()), 2)
        total_net = round(total_gross + fee_total, 2)
        total_earning = total_net if net_view else total_gross

        graph = {
            "month": month_name[int(month)],
            "year": str(year),
            "x_axis": x_axis,
            "report": report,
            "detail_earning": detail_rows,
            "total_earning": total_earning,
            "charity": round(total_earning * 0.025, 2),
            "title": "Month : %s %s ($ %s)"
            % (month_name[int(month)], year, total_earning),
            "tooltip": "'<b>Week : </b>'+this.x+'<br/>'+this.series.name+': $ '+this.y",
        }
    else:
        monthly = {i: 0.0 for i in range(1, 13)}
        fee_monthly = {i: 0.0 for i in range(1, 13)}
        for row in period_earning_rows:
            d = _effective_txn_date_any(row)
            if not d:
                continue
            if d.year != int(year):
                continue
            monthly[d.month] += float(row.get("amount") or 0)
        for row in period_fee_rows:
            d = _effective_txn_date_any(row)
            if not d:
                continue
            if d.year != int(year):
                continue
            fee_monthly[d.month] += float(row.get("amount") or 0)

        report = []
        for i in range(1, 13):
            gross = round(monthly[i], 2)
            fee = round(fee_monthly[i], 2)
            net = round(gross + fee, 2)
            report.append({"y": net if net_view else gross, "month": str(i)})

        total_gross = round(sum(monthly.values()), 2)
        total_net = round(total_gross + fee_total, 2)
        total_earning = total_net if net_view else total_gross

        graph = {
            "year": str(year),
            "x_axis": [
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
            ],
            "report": report,
            "detail_earning": [],
            "total_earning": total_earning,
            "charity": round(total_earning * 0.025, 2),
            "title": "Year : %s ($ %s)" % (year, total_earning),
            "tooltip": "'<b>'+this.x+'</b><br/>'+this.series.name+': $ '+this.y",
        }

    totals = defaultdict(float)
    fee_by_client = defaultdict(float)
    for row in period_earning_rows:
        client = _normalize_client_name(row.get("client_name") or "Unknown")
        totals[client] += float(row.get("amount") or 0)
    for row in period_fee_rows:
        client = _normalize_client_name(row.get("client_name") or "Unknown")
        fee_by_client[client] += float(row.get("amount") or 0)

    if net_view:
        for name, fee_amt in fee_by_client.items():
            totals[name] += float(fee_amt or 0)

    if len(totals) > 1:
        totals.pop("Unknown", None)

    data["graph"] = graph
    data["net_view"] = net_view
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

    return render(request, "upworkapi/total_earning_trx.html", data)


@login_required(login_url="/")
def all_time_earning_graph(request):
    data = {"page_title": "All Time Earning"}
    data["service_fee_total"] = 0.0

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
    unknown_rows = []
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
            hourly_details = hourly_graph.get("detail_earning") or []
            _accumulate_client_totals(client_totals, hourly_details)
            for d in hourly_details:
                client = _client_from_detail(d)
                if client != "Unknown" or _is_excluded_client_label(d, client):
                    continue
                amt = _amount_from_detail(d)
                if not amt:
                    continue
                unknown_rows.append(
                    {
                        "year": y,
                        "source": "hourly",
                        "date": d.get("date") or "",
                        "description": d.get("description") or "",
                        "amount": amt,
                    }
                )

            start_dt = date(y, 1, 1)
            end_dt = date(y, 12, 31)
            fixed_rows = _cached_fixed_price_transactions(
                request,
                token=token,
                freelancer_reference=freelancer_reference,
                tenant_id=tenant_id,
                tenant_ids=request.session.get("tenant_ids"),
                start_date=start_dt,
                end_date=end_dt,
            )
            fixed_total = 0.0
            for r in fixed_rows:
                amt = float(r.get("amount") or 0.0)
                if amt:
                    fixed_total += amt
                    client = _client_from_fixed(r)
                    if _is_excluded_client_label(r, client):
                        continue
                    client_totals[client] += amt
                    if client == "Unknown":
                        unknown_rows.append(
                            {
                                "year": y,
                                "source": "fixed",
                                "date": r.get("date") or r.get("created") or "",
                                "description": r.get("description") or "",
                                "amount": amt,
                            }
                        )

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
    try:
        start_dt = date(start_year, 1, 1)
        end_dt = date(current_year, 12, 31)
        _, fee_total, fee_debug = _service_fee_summary(
            request,
            start_date=start_dt,
            end_date=end_dt,
            include_rows=False,
            debug=True,
        )
        data["service_fee_total"] = fee_total
        data["service_fee_debug"] = fee_debug
    except Exception:
        pass

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
        if not _is_excluded_client_label({"description": name}, name)
    ]
    data["client_pie_data"] = json.dumps(
        [
            {"name": r["name"], "y": float(r["total"])}
            for r in data["client_rows"]
            if float(r["total"]) > 0
        ]
    )
    data["unknown_rows"] = sorted(
        unknown_rows, key=lambda row: abs(row.get("amount") or 0), reverse=True
    )

    return render(request, "upworkapi/all_time_earning.html", data)


@login_required(login_url="/")
def all_time_hourly_graph(request):
    data = {"page_title": "All Time Hourly"}

    token = request.session.get("token")
    if not token:
        messages.warning(request, "Missing token. Please login again.")
        return redirect("auth")

    current_year = datetime.now().year
    start_year = 2010
    years = list(range(start_year, current_year + 1))

    totals = []
    client_totals = defaultdict(float)
    try:
        for y in years:
            yearly_report = _cached_timereport_year(request, token, str(y))
            total_hours = float(yearly_report.get("total_hours") or 0)
            for row in yearly_report.get("client_rows") or []:
                client_totals[
                    _normalize_client_name(row.get("name") or "Unknown")
                ] += float(row.get("total") or 0)
            totals.append(round(total_hours, 2))
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
        "total_hours": total_earning,
        "title": "All Time Hourly : %s - %s (%s hrs)"
        % (x_axis[0], x_axis[-1], total_earning),
    }

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
        if not _is_excluded_client_label({"description": name}, name)
    ]
    data["client_pie_data"] = json.dumps(
        [
            {"name": r["name"], "y": float(r["total"])}
            for r in data["client_rows"]
            if float(r["total"]) > 0
        ]
    )
    return render(request, "upworkapi/all_time_hourly.html", data)


@login_required(login_url="/")
def all_time_hourly_year(request, year):
    data = {"page_title": "All Time Hourly"}

    if not re.match(r"^\d{4}$", str(year)):
        messages.warning(request, "Wrong year format.!")
        return redirect("all_time_hourly_graph")

    token = request.session.get("token")
    if not token:
        messages.warning(request, "Missing token. Please login again.")
        return redirect("auth")

    try:
        graph = _cached_timereport_year(request, token, str(year))
        data["graph"] = graph

        client_totals = defaultdict(float)
        for row in graph.get("client_rows") or []:
            client_totals[
                _normalize_client_name(row.get("name") or "Unknown")
            ] += float(row.get("total") or 0)

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
    except Exception as exc:
        messages.warning(request, f"Upwork API error: {exc}")
        data["graph"] = timereport_weekly(token, str(year))
        data["client_rows"] = []
        data["client_pie_data"] = json.dumps([])

    return render(request, "upworkapi/all_time_hourly_year.html", data)


@login_required(login_url="/")
def all_time_earning_year(request, year):
    data = {"page_title": "All Time Earning"}
    data["service_fee_total"] = 0.0

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
        start_dt = date(int(year), 1, 1)
        end_dt = date(int(year), 12, 31)
        _, fee_total, fee_debug = _service_fee_summary(
            request,
            start_date=start_dt,
            end_date=end_dt,
            include_rows=False,
            debug=True,
        )
        data["service_fee_total"] = fee_total
        data["service_fee_debug"] = fee_debug
    except Exception as exc:
        messages.warning(request, f"Upwork API error: {exc}")
        data["graph"] = earning_graph_annually(token, str(year))
        data["client_rows"] = []
        data["client_pie_data"] = json.dumps([])

    return render(request, "upworkapi/all_time_earning_year.html", data)


@login_required(login_url="/")
def all_time_earning_month(request, year, month):
    data = {"page_title": "All Time Earning"}
    data["service_fee_total"] = 0.0

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
        start_dt = date(int(year), int(month), 1)
        end_dt = date(int(year), int(month), monthrange(int(year), int(month))[1])
        _, fee_total, fee_debug = _service_fee_summary(
            request,
            start_date=start_dt,
            end_date=end_dt,
            include_rows=False,
            debug=True,
        )
        data["service_fee_total"] = fee_total
        data["service_fee_debug"] = fee_debug
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
    data["service_fee_total"] = 0.0

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
            tenant_ids=request.session.get("tenant_ids"),
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

    fee_rows = []
    try:
        fee_rows, fee_debug = fetch_transaction_history_rows(
            token=token,
            tenant_id=tenant_id,
            tenant_ids=request.session.get("tenant_ids"),
            start_date=start_dt,
            end_date=end_dt,
            debug=True,
        )
        fee_rows = [
            r
            for r in (fee_rows or [])
            if _is_txn_fee_row(r) and _is_txn_fixed_bonus_context(r)
        ]
        for r in fee_rows:
            d = _effective_txn_date_any(r)
            r["display_date"] = _display_date(
                d, fallback=str(r.get("date") or r.get("occurred_at") or "")
            )
        data["service_fee_total"] = sum(float(r.get("amount") or 0) for r in fee_rows)
        data["service_fee_debug"] = fee_debug
    except Exception:
        fee_rows = []

    clean = []
    total = 0.0

    for r in rows:
        occurred_at = (r.get("occurred_at") or "")[:10]
        amt = float(r.get("amount") or 0.0)
        if amt == 0:
            continue
        display_date = _display_date_str(occurred_at)

        client = r.get("client_name") or "Unknown"
        kind = r.get("kind") or ""
        desc = r.get("description") or ""

        clean.append(
            {
                "date": occurred_at,
                "display_date": display_date or occurred_at,
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
    data["service_fee_rows"] = fee_rows
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
    data["service_fee_total"] = 0.0

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
            tenant_ids=request.session.get("tenant_ids"),
            start_date=start_dt,
            end_date=end_dt,
        )
    except Exception as exc:
        messages.warning(request, f"Upwork API error: {exc}")
        rows = []

    fee_rows = []
    try:
        fee_rows, fee_debug = fetch_transaction_history_rows(
            token=token,
            tenant_id=tenant_id,
            tenant_ids=request.session.get("tenant_ids"),
            start_date=start_dt,
            end_date=end_dt,
            debug=True,
        )
        fee_rows = [
            r
            for r in (fee_rows or [])
            if _is_txn_fee_row(r) and _is_txn_fixed_bonus_context(r)
        ]
        for r in fee_rows:
            d = _effective_txn_date_any(r)
            r["display_date"] = _display_date(
                d, fallback=str(r.get("date") or r.get("occurred_at") or "")
            )
        data["service_fee_total"] = sum(float(r.get("amount") or 0) for r in fee_rows)
        data["service_fee_debug"] = fee_debug
        data["service_fee_rows"] = fee_rows
    except Exception:
        fee_rows = []

    clean = []
    total = 0.0

    for r in rows:
        occurred_at = (r.get("occurred_at") or "")[:10]
        amt = float(r.get("amount") or 0.0)
        if amt == 0:
            continue
        display_date = _display_date_str(occurred_at)

        client = r.get("client_name") or r.get("client") or "Unknown"
        kind = r.get("kind") or ""
        desc = r.get("description") or ""

        clean.append(
            {
                "date": occurred_at,
                "display_date": display_date or occurred_at,
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
        client_name = _normalize_client_name(item.get("client") or "Unknown")
        detail_rows.append(
            {
                "date": item.get("display_date") or _display_date_str(item["date"]),
                "client": client_name,
                "description": f'{client_name} - {item["description"]}',
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
        client = _get(d, "client_name") or _extract_client_name(d)
        client = _normalize_client_name(client)
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
