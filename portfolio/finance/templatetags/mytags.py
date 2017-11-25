from django import template
from django.template.defaultfilters import stringfilter
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

@register.filter(needs_autoescape=True)
@stringfilter
def colorize(amount, autoescape=True):
    if autoescape:
        value = escape(amount)
    if '0.00' in amount:
        color = 'black'
    elif '-' in amount:
        color = 'red'
    else:
        color = 'green'
    return mark_safe('<font color="{}">{}</font>'.format(color,amount))
    
@register.filter()
def currency(dollars):
    prefix = "" if dollars > -0.004 else "-"
    return "{}${:,.2f}".format(prefix, abs(dollars))

@register.filter()
def currencyround(dollars):
    prefix = "" if dollars > -0.004 else "-"
    return "{}${:,d}".format(prefix, abs(round(dollars)))

@register.filter()
def percentage(amount, decimals=2):
    return ("{:,."+str(decimals)+"f}%").format(amount*100)

@register.filter()
def parens(s):
    return "({})".format(s)
