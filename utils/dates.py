import datetime
from pendulum import Date


def week_ends(start, end=None):
    end = end or datetime.date.today()
    period = (Date.instance(start) - Date.instance(end))
    for week in period.range('weeks'):
        yield min(week.end_of('week'), Date.today())


def month_ends(start, end=None):
    end = end or datetime.date.today()
    period = (Date.instance(start) - Date.instance(end))
    for month in period.range('months'):
        yield min(month.end_of('month'), Date.today())


def year_ends(start, end=None):
    end = end or datetime.date.today()
    period = (Date.instance(start) - Date.instance(end))
    for year in period.range('years'):
        yield min(year.end_of('year'), Date.today())


def day_intervals(days, start, end=None):
    end = end or datetime.date.today()
    period = Date.instance(end) - Date.instance(start)
    return period.split('days', days)
