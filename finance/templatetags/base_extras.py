from django import template
from django.urls import resolve, Resolver404

register = template.Library()


@register.simple_tag
def navactive(request, viewname):
    try:
        match = resolve(request.path)
        if match.view_name == viewname: return 'active'
    except Resolver404:
        return ''
