import datetime
from decimal import Decimal, InvalidOperation
from re import sub

from django import template
from django.template.defaultfilters import stringfilter
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def lookup(value, key):
    return value.get(key, '')


@register.filter
@stringfilter
def colorize(amount):
    try:
        amount_num = Decimal(sub(r'[^\d.-]', '', amount))
    except InvalidOperation:
        return amount
    if abs(amount_num) == 0:
        color = 'black'
    elif amount_num < 0:
        color = 'red'
    else:
        color = 'green'
    return mark_safe('<font color="{}">{}</font>'.format(color, amount))


@register.filter
def currency(dollars, symbol=''):
    if dollars == '' or dollars is None:
        return ''
    return '{}{}${:,.2f}'.format('-' if dollars < -0.004 else '', symbol, abs(dollars))


@register.filter
def currencyround(dollars, symbol=''):
    if dollars == '' or dollars is None:
        return ''
    return '{}{}${:,d}'.format('-' if dollars < -0.004 else '', symbol, abs(round(dollars)))


@register.filter
def percentage(amount, decimals=2):
    if amount == '' or amount is None:
        return amount
    return '{:,.{}f}%'.format(amount * 100, decimals)


@register.simple_tag
def normalize(amount, min=2, max=4):
    """
    Rounds to a variable number of decimal places - as few as necessary in the range [min,max]
    :param amount: A float, int, decimal.Decimal, or string.
    :param min: the minimum number of decimal places to keep
    :param max: the maximum number of decimal places to keep
    :return: string.
    """
    if not amount:
        return amount

    # To Decimal, round to highest desired precision
    d = round(Decimal(amount), max)
    s = str(d)

    # Truncate as many extra zeros as we are allowed to
    for i in range(max-min):
        if s[-1] == '0':
            s = s[:-1]

    if s[-1] == '.':
        s = s[:-1]

    return s


@register.filter
def drop_trailing(amount, decimals=2):
    """
    Removes trailing zeros, keeping at least a specified number.
    :param amount: A float, int, decimal.Decimal, or string.
    :param decimals: the minimum number of decimal places to keep
    :return: string.
    """
    if not amount:
        return amount

    s = str(float(amount)).rstrip('0')
    if decimals == 0:
        return s.rstrip('.')

    num_decimals = len(s.split('.')[1])
    num_to_add = decimals - num_decimals
    if num_to_add <= 0:
        return s

    return s + '0' * num_to_add


@register.filter
def inverse(num):
    return 1 / num


@register.filter
@stringfilter
def prefix_plusminus(num):
    if not num or float(num) < 0:
        return num
    return '+' + num


@register.filter
def parens(s):
    return '({})'.format(s)


@register.filter
def prev_day(day):
    return day - datetime.timedelta(days=1)


@register.filter
def next_day(day):
    return day + datetime.timedelta(days=1)


@register.filter
def gain_word(capital_gain):
    return 'gain' if capital_gain >= 0 else 'loss'
