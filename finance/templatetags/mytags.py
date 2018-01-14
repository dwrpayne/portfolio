import datetime
from decimal import Decimal
from re import sub

from django import template
from django.template.defaultfilters import stringfilter
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def lookup(value, key):
    return value.get(key, '')


@register.filter()
@stringfilter
def colorize(amount):
    amount_num = Decimal(sub(r'[^\d.-]', '', amount))
    if abs(amount_num) == 0:
        color = 'black'
    elif amount_num < 0:
        color = 'red'
    else:
        color = 'green'
    return mark_safe('<font color="{}">{}</font>'.format(color, amount))


@register.filter()
def currency(dollars, decimals=2):
    if dollars == '': return ''
    prefix = "" if dollars > -0.004 else "-"
    return '{}${:,.{}f}'.format(prefix, abs(dollars), decimals)


@register.filter()
def currencyround(dollars):
    prefix = '' if dollars > -0.004 else '-'
    return '{}${:,d}'.format(prefix, abs(round(dollars)))


@register.filter()
def percentage(amount, decimals=2):
    return '{:,.{}f}%'.format(amount * 100, decimals)


@register.filter()
def prefix_plusminus(num):
    if not num or float(num) < 0:
        return num
    return '+' + num


@register.filter()
def parens(s):
    return '({})'.format(s)

@register.filter()
def prev_day(day):
    return day - datetime.timedelta(days=1)

@register.filter()
def next_day(day):
    return day + datetime.timedelta(days=1)
