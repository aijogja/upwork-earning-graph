from django import template
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch


register = template.Library()


@register.simple_tag(takes_context=True)
def active(context, urlname, *args):
    try:
        pattern = reverse(urlname, args=args)
    except NoReverseMatch:
        pattern = urlname
    path = context['request'].path
    if pattern == path:
        return 'active'
    return ''
