import datetime
import pendulum


def week_ends(start, end = datetime.date.today()):
    period = (pendulum.Date.instance(start) - pendulum.Date.instance(end))
    for week in period.range('weeks'):
        yield min(week.end_of('week'), pendulum.Date.today())
        
def month_ends(start, end = datetime.date.today()):
    period = (pendulum.Date.instance(start) - pendulum.Date.instance(end))
    for month in period.range('months'):
        yield min(month.end_of('month'), pendulum.Date.today())

def year_ends(start, end = datetime.date.today()):
    period = (pendulum.Date.instance(start) - pendulum.Date.instance(end))
    for year in period.range('years'):
        yield min(year.end_of('year'), pendulum.Date.today())