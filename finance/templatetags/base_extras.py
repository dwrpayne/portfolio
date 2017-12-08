from django import template
from django.core.urlresolvers import reverse, resolve, Resolver404

register = template.Library()


@register.simple_tag
def navactive(request, viewname):
    try:
        match = resolve(request.path)
        if match.view_name == viewname: return 'active'
    except Resolver404:
        return ''