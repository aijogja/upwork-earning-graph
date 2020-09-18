from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from upworkapi.utils import upwork_client
from datetime import datetime, timedelta
from calendar import monthrange, month_name
from upwork.routers import auth
from upwork.routers.reports.finance import earnings
from upwork.routers.reports import time
from upwork.routers.organization import users
from urllib.parse import quote
import re


def finreport_annually(client, year):
    list_month = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May',
                  'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    # query data
    user = auth.Api(client).get_user_info()
    query = """
        SELECT date, amount WHERE date >= '{0}-01-01' AND date <= '{0}-12-31'
    """.format(year)
    finreport = earnings.Gds(client).get_by_freelancer(
        user['info']['ref'],
        {'tq': quote(query)}
    )
    # extract data
    list_month_num = []
    list_report = []
    amount = 0
    if 'status' not in finreport:
        for row in finreport['table']['rows']:
            i = 0
            for k in row['c']:
                i += 1
                if i == 1:  # index for date -> 1
                    date = k['v']
                    num = date[4:-2]
                else:
                    amount = k['v']
            if num not in list_month_num:
                list_month_num.append(num)
            list_report.append({
                'date': date,
                'amount': amount
            })
    # process data
    list_earning = []
    total_earning = 0
    for k, v in enumerate(list_month):
        month_earn = 0
        for m in list_month_num:
            if int(m) == k:
                total = 0
                for dt in list_report:
                    if dt['date'][4:-2] == m:
                        total = total + float(dt['amount'])
                month_earn = round(total, 2)
                total_earning = round(total_earning + total, 2)
        list_earning.append({'y': month_earn, 'month': str(k)})

    list_month.pop(0), list_earning.pop(0)
    tooltip = "'<b>'+this.x+'</b><br/>'+this.series.name+': $ '+this.y"
    data = {
        'year': year,
        'x_axis': list_month,
        'report': list_earning,
        'total_earning': total_earning,
        'charity': round(total_earning * 0.025, 2),
        'title': 'Year : %s ($ %s)' % (year, total_earning),
        'tooltip': tooltip
    }
    return data


def finreport_monthly(client, year, month):
    list_day = ['']
    count_day = monthrange(year, month)[1]
    for i in range(1, (count_day + 1)):
        list_day.append(i)
    year = str(year)
    month = str('0' + str(month))[-2:]
    count_day = str(count_day)
    # query data
    user = auth.Api(client).get_user_info()
    query = """
        SELECT date, amount, description WHERE date >= '{0}-{1}-01'
        AND date <= '{0}-{1}-{2}'
    """.format(year, month, count_day)
    finreport = earnings.Gds(client).get_by_freelancer(
        user['info']['ref'],
        {'tq': quote(query)}
    )
    # extract data
    list_date = []
    list_report = []
    amount = 0
    for row in finreport['table']['rows']:
        i = 0
        for k in row['c']:
            i += 1
            if i == 1:  # index for date
                num = k['v'][-2:]
            elif i == 2:   # index for amount
                amount = k['v']
            else:
                desc = k['v']
        if num not in list_date:
            list_date.append(num)
        list_report.append({
            'date': int(num),
            'amount': amount,
            'description': desc
        })
    # process data
    list_report = sorted(list_report, key=lambda k: k['date'])
    list_earning = []
    total_earning = 0
    for k, v in enumerate(list_day):
        weekly_earn = 0
        for t in list_date:
            if int(t) == k:
                total = 0
                for dt in list_report:
                    if dt['date'] == int(t):
                        total = total + float(dt['amount'])
                weekly_earn = round(total, 2)
                total_earning = round((total_earning + total), 2)
        list_earning.append(weekly_earn)

    list_day.pop(0), list_earning.pop(0)
    tooltip = "'<b>Date : </b>'+this.x+'<br/>'+this.series.name+': $ '+this.y"
    data = {
        'month': month_name[int(month)],
        'year': year,
        'x_axis': list_day,
        'report': list_earning,
        'detail_earning': list_report,
        'total_earning': total_earning,
        'charity': round(total_earning * 0.025, 2),
        'title': 'Month : %s %s ($ %s)' % (
            month_name[int(month)], year, total_earning
        ),
        'tooltip': tooltip
    }
    return data


def timereport_weekly(client, year):
    current_week = datetime.now().isocalendar()[1] - 1
    if current_week == 0:
        current_week = 1
    last_week = datetime.strptime(
        '%s1231' % year, '%Y%m%d').isocalendar()[1]
    if last_week == 1:
        last_week = 52
    list_week = [str(i) for i in range(1, last_week+1)]
    # query data
    user_detail = users.Api(client).get_my_info()
    query = """
        SELECT worked_on, hours WHERE worked_on <= '{year}-12-31'
        AND worked_on >= '{year}-01-01'
    """.format(year=year)
    timereport = time.Gds(client).get_by_freelancer_limited(
        user_detail['user']['id'],
        {'tq': quote(query)}
    )
    # extract data
    weeks = {}
    timelog = 0
    total_hours = 0
    if 'status' not in timereport:
        for row in timereport['table']['rows']:
            i = 0
            for k in row['c']:
                i += 1
                if i == 1:  # index untuk date -> 1
                    date = k['v']
                    week_num = datetime.strptime(
                        date, '%Y%m%d').isocalendar()[1]
                else:
                    timelog = float(k['v'])
            if weeks.get(week_num):
                weeks[week_num].append(timelog)
            else:
                weeks[week_num] = [timelog]
    # process data
    weekly_report = []
    for week in list_week:
        if weeks.get(int(week)):
            hours = sum(weeks.get(int(week)))
        else:
            hours = 0
        total_hours += hours
        weekly_report.append(hours)
    avg_week = round(int(total_hours)/current_week, 2)
    work_status = 'success'
    if avg_week < 20:
        work_status = 'danger'
    elif avg_week < 40:
        work_status = 'warning'
    tooltip = "'<b>Week '+this.x+'</b><br/>Hour: '+formating_time(this.y)"
    data = {
        'year': year,
        'x_axis': list_week,
        'report': weekly_report,
        'total_hours': int(total_hours),
        'avg_week': int(avg_week),
        'work_status': work_status,
        'title': 'Year : %s' % (year),
        'tooltip': tooltip,
    }
    return data


@login_required(login_url='/')
def earning_graph(request):
    data = {'page_title': 'Earning Graph'}
    client = upwork_client.get_authenticated_client(
        request.session['upwork_auth']['access_token'],
        request.session['upwork_auth']['access_token_secret'],
    )

    if request.method == 'POST':
        year = request.POST.get('year')
        month = request.POST.get('month')
        if not re.match('^[0-9]+$', year) or len(year) != 4:
            messages.warning(request, "Wrong year format.!")
            return redirect('earning_graph')

        if month:
            finreport = finreport_monthly(client, int(year), int(month))
        else:
            finreport = finreport_annually(client, year)
    else:
        now = datetime.now()
        year = str(now.year)
        finreport = finreport_annually(client, year)

    data['graph'] = finreport
    return render(request, 'upworkapi/finance.html', data)


@login_required(login_url='/')
def timereport_graph(request):
    data = {'page_title': 'Time Report Graph'}
    client = upwork_client.get_authenticated_client(
        request.session['upwork_auth']['access_token'],
        request.session['upwork_auth']['access_token_secret'],
    )

    if request.method == 'POST':
        year = request.POST.get('year')
        if not re.match('^[0-9]+$', year) or len(year) != 4:
            messages.warning(request, "Wrong year format.!")
            return redirect('timereport_graph')
    else:
        now = datetime.now()
        year = str(now.year)

    timelog = timereport_weekly(client, year)
    data['graph'] = timelog
    return render(request, 'upworkapi/timereport.html', data)
