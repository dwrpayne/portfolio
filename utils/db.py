from datetime import date, timedelta


class SecurityMixinQuerySet:
    def for_security(self, symbol):
        return self.filter(security=symbol)

    def for_securities(self, security_iter):
        return self.filter(security__in=security_iter)


class DayMixinQuerySet:
    day_field = 'day'

    def today(self):
        return self.at_date(date.today())

    def yesterday(self):
        return self.at_date(date.today() - timedelta(days=1))

    def at_date(self, date):
        return self.filter(**{self.day_field: date})

    def after(self, start):
        return self.filter(**{self.day_field + '__gte': start})

    def before(self, end):
        return self.filter(**{self.day_field + '__lte': end})

    def between(self, start, end):
        return self.filter(**{self.day_field + '__range': (start, end)})

    def in_year(self, year):
        return self.filter(**{self.day_field + '__year': year})
