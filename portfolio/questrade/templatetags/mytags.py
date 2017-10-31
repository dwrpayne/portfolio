from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

@register.filter(needs_autoescape=True)
def colorize(amount, autoescape=True):
    s = str(amount)
    if autoescape:
        value = escape(s)
    if '0.00' in s:
        color = 'black'
    elif '-' in s:
        color = 'red'
    else:
        color = 'green'
    return mark_safe('<font color="{}">{}</font>'.format(color,s))
    
@register.filter()
def currency(dollars):
    prefix = "" if dollars > -0.004 else "-"
    return "{}${:,.2f}".format(prefix, abs(dollars))

@register.filter()
def percentage(amount):
    return "({:,.2f}%)".format(amount*100)
