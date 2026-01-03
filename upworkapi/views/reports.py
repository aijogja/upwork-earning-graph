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


def _month_week_ranges(year: int, month: int):
    first = datetime(year, month, 1).date()
    if month == 12:
        next_month = datetime(year + 1, 1, 1).date()
    else:
        next_month = datetime(year, month + 1, 1).date()
    last = next_month - timedelta(days=1)

    start = first - timedelta(days=first.weekday())      # Monday
    end = last + timedelta(days=(6 - last.weekday()))    # Sunday

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
    # query
    query = """query User {
            user {
                freelancerProfile {
                    user {
                        timeReport(timeReportDate_bt: { rangeStart: "%s0101", rangeEnd: "%s1231" }) {
                            dateWorkedOn
                            totalCharges
                            task
                            memo
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
    # processing data
    list_earning = []
    total_earning = 0
    earning_report = response["data"]["user"]["freelancerProfile"]["user"]["timeReport"]
    for k, v in enumerate(list_month, start=1):
        month_earn = 0
        total = 0
        for m in earning_report:
            if int(m["dateWorkedOn"][5:-3]) == k:
                # compare number of month
                total = total + float(m["totalCharges"])
        month_earn = round(total, 2)
        total_earning = round(total_earning + total, 2)
        list_earning.append({"y": month_earn, "month": str(k)})

    tooltip = "'<b>'+this.x+'</b><br/>'+this.series.name+': $ '+this.y"
    data = {
        "year": year,
        "x_axis": list_month,
        "report": list_earning,
        "total_earning": total_earning,
        "charity": round(total_earning * 0.025, 2),
        "title": "Year : %s ($ %s)" % (year, total_earning),
        "tooltip": tooltip,
    }
    return data


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

    # init buckets
    week_totals = {wlabel: 0.0 for wlabel in x_axis}
    list_report = []
    total_earning = 0.0

    for m in earning_report:
        d = datetime.strptime(m["dateWorkedOn"], "%Y-%m-%d").date()
        amt = float(m["totalCharges"])

        # find which week range contains the date
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
    # mapping weeks
    current_week = datetime.now().isocalendar()[1] - 1
    if current_week == 0:
        current_week = 1
    last_week = datetime.strptime("%s1231" % year, "%Y%m%d").isocalendar()[1]
    if last_week == 1:
        last_week = 52
    list_week = [str(i) for i in range(1, last_week + 1)]
    # query
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
    # processing data
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
    # threshold
        selected_year = int(year)
        today = date.today()

        # pembagi average
        if selected_year == today.year:
            divisor_week = today.isocalendar()[1]   # minggu berjalan tahun ini
        else:
            divisor_week = last_week                # tahun lampau: total minggu tahun itu (52/53)

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
def earning_graph(request):
    data = {"page_title": "Earning Graph"}

    year = request.GET.get("year") or request.POST.get("year") or str(datetime.now().year)
    month = request.POST.get("month") 

    if not re.match(r"^[0-9]{4}$", str(year)):
        messages.warning(request, "Wrong year format.!")
        return redirect("earning_graph")

    if month:
        finreport = earning_graph_monthly(request.session["token"], int(year), int(month))
    else:
        finreport = earning_graph_annually(request.session["token"], str(year))

    data["graph"] = finreport
    return render(request, "upworkapi/finance.html", data)


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
