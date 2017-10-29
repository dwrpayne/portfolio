from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

@register.filter(needs_autoescape=True)
def colorize(amount, autoescape=True):
    s = str(amount)
    if autoescape:
        value = escape(s)
    if '-' in s:
        result = '<font color="red">{}</font>'.format(s)
    else:
        result = '<font color="green">{}</font>'.format(s)
    return mark_safe(result)
    
@register.filter()
def currency(dollars):
    prefix = "" if dollars > 0 else "-"
    return "{}${:,.2f}".format(prefix, abs(dollars))

@register.filter()
def percentage(amount):
    return "({:,.2f}%)".format(amount*100)
