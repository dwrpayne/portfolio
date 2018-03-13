import datetime
import decimal
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
    try:
        amount_num = decimal.Decimal(sub(r'[^\d.-]', '', amount))
    except decimal.InvalidOperation:
        return amount
    if abs(amount_num) == 0:
        color = 'black'
    elif amount_num < 0:
        color = 'red'
    else:
        color = 'green'
    return mark_safe('<font color="{}">{}</font>'.format(color, amount))


@register.filter()
def currency(dollars, symbol=''):
    if dollars == '' or dollars is None:
        return ''
    return '{}{}${:,.2f}'.format('-' if dollars < -0.004 else '', symbol, abs(dollars))


@register.filter()
def currencyround(dollars, symbol=''):
    if dollars == '' or dollars is None:
        return ''
    return '{}{}${:,d}'.format('-' if dollars < -0.004 else '', symbol, abs(round(dollars)))


@register.filter()
def percentage(amount, decimals=2):
    if amount == '' or amount is None:
        return amount
    return '{:,.{}f}%'.format(amount * 100, decimals)


@register.filter()
def inverse(num):
    return 1 / num


@register.filter()
@stringfilter
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


@register.filter()
def gain_word(capital_gain):
    return 'gain' if capital_gain >= 0 else 'loss'
